"""Request core of the Paladin deployment: identity -> delegation -> ledger -> Engine pipeline inside ONE world transaction.

Every effect is committed by the Engine's action pipeline (gate order: identity, inputs, stale, authority, preconditions,
policies, approval, gate-pass, constraints, adapters). The world file is canonical truth: the Engine State is rebuilt from
it before each request, and adapters write into it inside the request's transaction (rolled back on any failure).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from typing import Any, Callable

from paladin.authcompile import delegation_table
from paladin.boot import boot
from paladin.engine import CapabilityError, InvalidRequest, Principal
from paladin.engine import canon, gates
from paladin.ledger import Ledger
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


class Crash(BaseException):
    """Simulated process death at an armed point (PROT-H23-A8). A BaseException: no `except Exception` may swallow it."""

    def __init__(self, point: str):
        super().__init__(point)
        self.point = point


class _Rollback(Exception):
    def __init__(self, result: CallResult):
        self.result = result


def fingerprint(*parts: Any) -> str:
    return canon.digest(list(parts))


def plain(x: Any) -> Any:
    return copy.deepcopy(canon.to_plain(x))


class Core:
    def __init__(self, domain, factory, verifier, ops_spec, auth_spec, clock, mutants, state_dir=None,
                 hook: Callable[[str], None] = lambda point: None, restart: bool = False):
        self.domain, self._factory, self._verifier, self.clock, self.mutants = domain, factory, verifier, clock, mutants
        self.hook = hook  # crash-injection point callback (before_commit fires inside the adapters, after_commit in run)
        self.state_dir = state_dir or tempfile.mkdtemp(prefix="paladin-state-")  # a private dir even when none is given
        self.lock = threading.RLock()  # the Engine State, the service connection and the ledger are single-writer
        self._svc = factory("paladin-service")
        self.ops_spec = ops_spec
        self.ops = {o["name"]: o for o in ops_spec["operations"]}
        self.reads = {r["name"] for r in ops_spec["reads"]}
        # canonical writes share ONE world transaction (all-or-nothing); external effects are single atomic adapter writes
        # through each system's own handle (a second SQLite connection cannot write inside the service transaction)
        self._canonical = any(e["kind"] != "external" for o in ops_spec["operations"] for e in o["effects"])
        # durable write-ahead ledger + single-use approvals + authority in force (see paladin.ledger)
        self.ledger = Ledger(os.path.join(self.state_dir, "ledger.sqlite"), volatile="ledger_after_commit_volatile" in mutants)
        self.authority_version = 0
        self._mut_n = 0
        self._attempts = self.ledger.get_meta("attempts") or 0
        persisted = self.ledger.get_meta("auth_spec") if restart else None  # restart: the authority in force at the crash wins over the deploy-time spec
        self.set_authority(persisted if persisted is not None else auth_spec)
        if not self.ledger.volatile:
            self.recovered = self.ledger.recover(self.world_digest())  # resolve a request left in doubt by a crash

    # ---- authority --------------------------------------------------------------------------
    def set_authority(self, auth_spec: dict) -> int:
        validate_strict(auth_spec, self.ops_spec)  # R-4: shared strict control, before anything changes (ValueError)
        self.auth = copy.deepcopy(auth_spec)
        self.booted = boot(self.domain, self.ops_spec, self.auth, self._factory, self._svc, self.clock.now,
                           lambda: self.hook("before_commit"))
        self.ledger.put_meta("auth_spec", self.auth)
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

    def world_digest(self) -> str:
        """Digest of the whole canonical + external world as the service sees it (witness for crash recovery)."""
        st = state_from_world(self.eng.model, self._svc)
        snap = {"o": sorted(f"{t}:{k}:{json.dumps(v['props'], sort_keys=True)}:{v['ver']}" for (t, k), v in st.objects.items()),
                "l": sorted(repr(k) for k in st.links), "e": [(e["seq"], e["payload"]) for e in self._svc.external_effects()]}
        return hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()

    def _guard(self):
        """The variant's concurrency control for the authorize -> commit section (MUTANT unsynchronized_commit drops it)."""
        return contextlib.nullcontext() if "unsynchronized_commit" in self.mutants else self.lock

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
        with self._guard():
            led = self.ledger.get(rid)
            if led is not None:
                if led["state"] != "COMMITTED":
                    return CallResult("UNAVAILABLE", {"reason": "request in flight"})
                return self._replay(led, who, bypass, fp, sub, obo, op, clean, rid)
            self._attempts += 1  # the Engine's own idempotency map is per attempt; request-id idempotency is the ledger's job
            attempt = self._attempts
            self.ledger.put_meta("attempts", attempt)
            self.ledger.prepare(rid, fp, self.world_digest(), sub, obo, op)  # durable BEFORE any world write
            try:
                res = self._commit(BYPASS if bypass else who, op, clean, f"{rid}~{attempt}", fp, rid)
                if res.status == "OK":
                    self.hook("after_commit")  # crash here: world committed, ledger still PREPARED (recovered at restart)
                    self.ledger.finalize(rid, fp, sub, obo, op, res.status, plain(res.body))
                else:
                    self.ledger.abort(rid)
            except Crash:
                raise
            except BaseException:
                self.ledger.abort(rid)
                raise
            return res

    def _replay(self, led, who, bypass, fp, sub, obo, op, clean, rid) -> CallResult:
        if led["fp"] == fp:  # R5: same request -> never a second effect, decided against the authority in force NOW
            if not bypass and not self.allowed_now(who, op, clean):
                return CallResult("DENIED", {"gate": "authority", "reason": "authority changed since commit"})
            return CallResult(led["status"], {**plain(led["body"]), "replayed": True})
        if "mutable_gated_input" in self.mutants and (led["sub"], led["obo"], led["op"]) == (sub, obo, op):
            self._mut_n += 1  # MUTANT: decision reuse keyed by request_id only - changed gated inputs commit undecided
            return self._commit(BYPASS, op, clean, f"{rid}~m{self._mut_n}", fp, f"{rid}~m{self._mut_n}", False)
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

    def _commit(self, who: Principal, op: str, args: dict, key: str, fp: str, rid: str, journaled: bool = True) -> CallResult:
        """Propose; if the Engine parks it for approval, consume a matching single-use pre-approval and let the Engine's
        approval gate run in the same world transaction; without one the request is refused (zero effects)."""
        try:
            with (self._svc.transaction() if self._canonical else contextlib.nullcontext()):
                self.eng.store.current = state_from_world(self.eng.model, self._svc)
                rec = self.eng.propose(op, args, who, idempotency_key=key)
                if rec["state"] == "PENDING_APPROVAL":
                    approver = self.ledger.claim_approval(fp, rid)  # durable claim: one approval authorises one commit
                    if approver is None:
                        raise _Rollback(CallResult("DENIED", {"gate": "approval", "reason": "approval_required"}))
                    rec = self.eng.approve(rec["exec"], self.booted.principals[approver])
                res = self.map_record(rec)
                if res.status != "OK":
                    raise _Rollback(res)  # nothing but an OK commit may touch the world (R7)
            if not journaled:
                self.ledger.consume(rid)  # mutant path is not journaled: consume its claim here
            return res
        except _Rollback as r:
            self.ledger.release_approval(rid)
            return r.result
        except CapabilityError as exc:  # approver identity/capability refused by the Engine
            self.ledger.release_approval(rid)
            return CallResult("DENIED", {"gate": "approval", "reason": str(exc) or "approval refused"})
        except InvalidRequest as exc:
            self.ledger.release_approval(rid)
            return CallResult("INVALID", {"gate": "engine", "reason": str(exc) or "invalid request"})
        except Exception as exc:  # noqa: BLE001 - fail closed: the transaction was rolled back
            self.ledger.release_approval(rid)
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
