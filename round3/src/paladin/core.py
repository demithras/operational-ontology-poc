"""Request core of the Paladin deployment: identity -> delegation -> ledger -> Engine pipeline inside ONE world transaction.

Every effect is committed by the Engine's action pipeline (gate order: identity, inputs, stale, authority, preconditions,
policies, approval, gate-pass, constraints, adapters). The world file is canonical truth: the Engine State is rebuilt from
it before each request, and adapters write into it inside the request's transaction (rolled back on any failure).
"""
from __future__ import annotations

import contextlib
import copy
import json
from typing import Any

from paladin.authcompile import delegation_table
from paladin.boot import boot
from paladin.engine import CapabilityError, InvalidRequest, Principal
from paladin.engine import canon, gates
from paladin.worldbridge import state_from_world
from r3_shared.authspec import validate_strict
from r3_shared.identity import TokenError
from r3_shared.variant import CallResult

AUDIENCE = "paladin"
DENY_GATES = ("identity", "authority", "gate_pass", "approval", "policy")  # authority/approval/policy refusals are DENIED; schema, precondition, idempotency-key faults INVALID
BYPASS = Principal("paladin-bypass", frozenset({"admin"}), frozenset())  # used ONLY by the backstop_bypass / mutable_gated_input mutants


def _why(detail: Any) -> str:
    """Short human reason from a gate's detail: failed preconditions, or the applicable deny/approval policy refs."""
    d = plain(detail) if detail is not None else None
    if isinstance(d, dict):
        if d.get("failed"):
            return ": failed " + ", ".join(str(x) for x in d["failed"])[:200]
        refs = [r["ref"] for r in d.get("results", []) if r.get("applies") and r.get("decision") != "allow"]
        if refs:
            return ": " + ", ".join(refs)[:200]
    return f": {d}"[:200] if d not in (None, "", [], {}) else ""


class _Rollback(Exception):
    def __init__(self, result: CallResult):
        self.result = result


def fingerprint(*parts: Any) -> str:
    return canon.digest(list(parts))


def plain(x: Any) -> Any:
    return copy.deepcopy(canon.to_plain(x))


class Core:
    def __init__(self, domain, factory, verifier, ops_spec, auth_spec, clock, mutants):
        self.domain, self._factory, self._verifier, self.clock, self.mutants = domain, factory, verifier, clock, mutants
        self._svc = factory("paladin-service")
        self.ops_spec = ops_spec
        self.ops = {o["name"]: o for o in ops_spec["operations"]}
        self.reads = {r["name"] for r in ops_spec["reads"]}
        # canonical writes share ONE world transaction (all-or-nothing); external effects are single atomic adapter writes
        # through each system's own handle (a second SQLite connection cannot write inside the service transaction)
        self._canonical = any(e["kind"] != "external" for o in ops_spec["operations"] for e in o["effects"])
        self.ledger: dict[str, dict] = {}   # request_id -> committed request (fingerprint + result)
        self.approvals: dict[str, list] = {}  # request fingerprint -> unused pre-approvals (approver pids, FIFO, single use)
        self.authority_version = 0
        self._mut_n = 0
        self._attempts = 0
        self.set_authority(auth_spec)

    # ---- authority --------------------------------------------------------------------------
    def set_authority(self, auth_spec: dict) -> int:
        validate_strict(auth_spec, self.ops_spec)  # R-4: shared strict control, before anything changes (ValueError)
        self.auth = copy.deepcopy(auth_spec)
        self.booted = boot(self.domain, self.ops_spec, self.auth, self._factory, self._svc, self.clock.now)
        self.eng = self.booted.engine
        if {"backstop_bypass", "mutable_gated_input"} & set(self.mutants):
            self.eng.register_principal(BYPASS)  # exists ONLY in mutated deployments
        self.delegations = delegation_table(self.auth)
        self.delegator = {p["id"]: p["delegated_by"] for p in self.auth["principals"]}
        self.authority_version += 1
        return self.authority_version

    def chain_pids(self, pid: str) -> set:
        out = set()
        while pid is not None and pid not in out:
            out.add(pid)
            pid = self.delegator.get(pid)
        return out

    # ---- identity ---------------------------------------------------------------------------
    def subject(self, token: str, args: Any = None) -> str | None:
        """R1: the subject comes only from the verified token. (Mutant identity_substitution: an identity field wins.)"""
        try:
            sub = self._verifier.verify(token, AUDIENCE, self.clock)
        except TokenError:
            return None
        if "identity_substitution" in self.mutants and isinstance(args, dict):
            for f in ("principal", "actor", "requested_by", "owner"):
                if isinstance(args.get(f), str):
                    return args.pop(f)
        return sub

    def principal(self, sub: str, obo: Any, op: str | None) -> Principal | CallResult:
        """Delegate semantics (PROT-H23): a principal whose spec `delegated_by` is P is ALWAYS evaluated as P's delegate;
        on_behalf_of must be absent or P; a principal without a delegator that names on_behalf_of is DENIED."""
        p = self.booted.principals.get(sub)
        if p is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "unknown principal"})
        eff = self.delegator.get(sub)
        if obo is not None and (eff is None or obo != eff):
            return CallResult("DENIED", {"gate": "delegation", "reason": "on_behalf_of does not name this principal's delegator"})
        if eff is None:
            return p
        d = self.booted.principals.get(eff)
        if d is None or (op is not None and op not in self.delegations.get((sub, eff), frozenset())):
            return CallResult("DENIED", {"gate": "delegation", "reason": "no delegation for this operation"})
        return Principal(p.pid, p.roles, p.relations, d)

    # ---- the request ------------------------------------------------------------------------
    def check_shape(self, op: str, args: Any, rid: Any) -> CallResult | dict:
        spec = self.ops[op]
        if not isinstance(args, dict):
            return CallResult("INVALID", {"gate": "inputs", "reason": "args must be an object"})
        names = {i["name"] for i in spec["inputs"]}
        extra = sorted(k for k in args if k not in names)
        if extra:  # identity-like or unknown fields never select authority: rejected (R1)
            return CallResult("INVALID", {"gate": "inputs", "reason": f"unknown argument(s) {extra}"})
        if not isinstance(rid, str) or not rid:
            return CallResult("INVALID", {"gate": "request", "reason": "request_id required"})
        try:
            return json.loads(json.dumps(args))  # R4: the request owns a private copy of its inputs
        except (TypeError, ValueError):
            return CallResult("INVALID", {"gate": "inputs", "reason": "args are not JSON values"})

    def run(self, sub: str, obo: Any, op: str, args: Any, rid: Any, via: str) -> CallResult:
        if op not in self.ops:
            return CallResult("UNKNOWN", {"reason": "unknown operation"})
        who = self.principal(sub, obo, op)
        if isinstance(who, CallResult):
            return who
        clean = self.check_shape(op, args, rid)
        if isinstance(clean, CallResult):
            return clean
        obo = self.delegator.get(sub)  # a delegate's request is the same request with or without on_behalf_of
        bypass = via == "direct" and "backstop_bypass" in self.mutants
        fp = fingerprint(sub, obo, op, clean)
        led = self.ledger.get(rid)
        if led is not None:
            return self._replay(led, who, bypass, fp, sub, obo, op, clean, rid)
        self._attempts += 1  # the Engine's own idempotency map is per attempt; request-id idempotency is the ledger's job
        res = self._commit(BYPASS if bypass else who, op, clean, f"{rid}~{self._attempts}", fp)
        if res.status == "OK":
            self.ledger[rid] = {"fp": fp, "status": res.status, "body": plain(res.body), "sub": sub, "obo": obo, "op": op}
        return res

    def _replay(self, led, who, bypass, fp, sub, obo, op, clean, rid) -> CallResult:
        if led["fp"] == fp:  # R5: same request -> never a second effect, decided against the authority in force NOW
            if not bypass and not self.allowed_now(who, op, clean):
                return CallResult("DENIED", {"gate": "authority", "reason": "authority changed since commit"})
            return CallResult(led["status"], {**plain(led["body"]), "replayed": True})
        if "mutable_gated_input" in self.mutants and (led["sub"], led["obo"], led["op"]) == (sub, obo, op):
            self._mut_n += 1  # MUTANT: decision reuse keyed by request_id only - changed gated inputs commit undecided
            return self._commit(BYPASS, op, clean, f"{rid}~m{self._mut_n}", fp)
        return CallResult("INVALID", {"gate": "request", "reason": "request_id already used for a different request"})

    def allowed_now(self, who: Principal, op: str, args: dict) -> bool:
        self.eng.store.current = state_from_world(self.eng.model, self._svc)
        spec = self.eng.model.get("actions", op)
        res = gates.resources_of(self.eng, spec, args)
        return self.eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who,
                                 capability=f"action:{op}", resources=res, view=self.eng.read_view()).allowed

    def holds_approval(self, approver: str, op: str, args: dict) -> bool:
        """Does the approver hold the approval capability of `op` for these inputs (same decision the Engine gate makes)."""
        from paladin.engine import pipeline
        self.eng.store.current = state_from_world(self.eng.model, self._svc)
        spec = self.eng.model.get("actions", op)
        res = gates.resources_of(self.eng, spec, args)
        who = self.booted.principals[approver]
        return any(self.eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who, capability=cap,
                                     resources=res, view=self.eng.read_view()).allowed
                   for cap in pipeline.approval_capabilities(self.eng, spec))

    def _commit(self, who: Principal, op: str, args: dict, key: str, fp: str) -> CallResult:
        """Propose; if the Engine parks it for approval, consume a matching single-use pre-approval and let the Engine's
        approval gate run in the same world transaction; without one the request is refused (zero effects)."""
        try:
            with (self._svc.transaction() if self._canonical else contextlib.nullcontext()):
                self.eng.store.current = state_from_world(self.eng.model, self._svc)
                rec = self.eng.propose(op, args, who, idempotency_key=key)
                if rec["state"] == "PENDING_APPROVAL":
                    pre = self.approvals.get(fp)
                    if not pre:
                        raise _Rollback(CallResult("DENIED", {"gate": "approval", "reason": "approval_required"}))
                    rec = self.eng.approve(rec["exec"], self.booted.principals[pre[0]])
                res = self.map_record(rec)
                if res.status != "OK":
                    raise _Rollback(res)  # nothing but an OK commit may touch the world (R7)
            if rec.get("approvals") and self.approvals.get(fp):
                self.approvals[fp].pop(0)  # one approval authorises at most one commit
            return res
        except _Rollback as r:
            return r.result
        except CapabilityError as exc:  # approver identity/capability refused by the Engine
            return CallResult("DENIED", {"gate": "approval", "reason": str(exc) or "approval refused"})
        except InvalidRequest as exc:
            return CallResult("INVALID", {"gate": "engine", "reason": str(exc) or "invalid request"})
        except Exception as exc:  # noqa: BLE001 - fail closed: the transaction was rolled back
            return CallResult("UNAVAILABLE", {"reason": f"{type(exc).__name__}: {exc}"})

    def map_record(self, rec: dict) -> CallResult:
        st = rec["state"]
        base = {"state": st, "execution": rec["exec"]}
        if st == "DENIED":
            bad = next((g for g in rec["gates"] if g.get("passed") is False), None)
            name = bad["gate"] if bad else "policy"
            detail = bad.get("detail") if bad else None
            reason = f"{name} gate refused" + _why(detail)
            return CallResult("DENIED" if name in DENY_GATES else "INVALID", {**base, "gate": name, "reason": reason})
        if st == "PENDING_APPROVAL":
            return CallResult("DENIED", {**base, "gate": "approval", "reason": "approval_required"})
        if rec["adapter_errors"]:
            return CallResult("UNAVAILABLE", {**base, "gate": "adapter", "reason": "dependency unavailable",
                                              "detail": [e["error"] for e in rec["adapter_errors"]]})
        return CallResult("OK", {**base, "effects": list(rec["effect_ids"])})
