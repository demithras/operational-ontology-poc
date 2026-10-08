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
import time
from typing import Any, Callable

from paladin import capgraph, evid
from paladin.authcompile import delegation_table
from paladin.boot import boot
from paladin.engine import CapabilityError, InvalidRequest, Principal
from paladin.engine import canon, gates
from paladin.core_g2 import G2Mixin, Rollback
from paladin.core_g3 import G3Mixin
from paladin.sovchan import SovMixin
from paladin.sovprov import SovProvMixin
from paladin.histledger import HistLedger
from paladin.ledger import Ledger
from paladin.worldbridge import state_from_world, tx_rows
from r3_shared.anchor import AnchorError
from r3_shared.authgraph import authority_digest
from r3_shared.evidence import canonical_bytes
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


_Rollback = Rollback


def fingerprint(*parts: Any) -> str:
    return canon.digest(list(parts))


def plain(x: Any) -> Any:
    return copy.deepcopy(canon.to_plain(x))


class Core(G3Mixin, SovMixin, SovProvMixin, G2Mixin):
    def __init__(self, domain, factory, verifier, ops_spec, auth_spec, clock, mutants, state_dir=None,
                 hook: Callable[[str], None] = lambda point: None, restart: bool = False, history=None, anchor=None,
                 stream=None, governance=None):
        self.domain, self._factory, self._verifier, self.clock, self.mutants = domain, factory, verifier, clock, mutants
        self.hook = hook  # crash-injection point callback (before_commit fires inside the adapters, after_commit in run)
        self.lock = threading.RLock()  # the Engine State, the service connection and the ledger are single-writer
        self._mutant_io = threading.RLock()  # used ONLY by the unsynchronized_commit mutant (serialises storage I/O, not the check)
        self.ops_spec = ops_spec
        self.g2_init(history, anchor, stream, mutants)
        self._svc = self.handle("paladin-service")
        self.ops = {o["name"]: o for o in ops_spec["operations"]}
        self.reads = {r["name"] for r in ops_spec["reads"]}
        # canonical writes share ONE world transaction (all-or-nothing); external effects are single atomic adapter writes
        # through each system's own handle (a second SQLite connection cannot write inside the service transaction)
        self._canonical = any(e["kind"] != "external" for o in ops_spec["operations"] for e in o["effects"])
        # durable write-ahead ledger + single-use approvals + authority in force (see paladin.ledger / paladin.histledger)
        if history is not None:  # H27 runs: every durable record lives in the (attackable) HistoryStore, no state_dir
            self.state_dir, self.ledger = None, HistLedger(history)
        else:
            self.state_dir = state_dir or tempfile.mkdtemp(prefix="paladin-state-")  # a private dir even when none is given
            os.makedirs(self.state_dir, exist_ok=True)
            self.ledger = Ledger(os.path.join(self.state_dir, "ledger.sqlite"), volatile="ledger_after_commit_volatile" in mutants)
        self._mut_n = 0
        self._attempts = self.ledger.get_meta("attempts") or 0
        persisted = self.ledger.get_meta("auth_spec") if (restart or history is not None) else None  # the authority in force wins over the deploy-time spec
        self.auth_fault = None  # E-7: set when the authority record in the history is unusable; mutating calls then fail closed
        self.recovered = []
        try:
            if persisted is None and history is not None and history.keys("auth/"):
                raise ValueError("authority record missing from a non-empty history")  # deleted record = rollback attempt
            if persisted is not None and history is not None:  # the record must match its content-addressed copy
                if history.get(f"auth/{authority_digest(persisted)}") != canonical_bytes(persisted):
                    raise ValueError("authority record does not match its digest-addressed copy")
                self.install(persisted, persist=False)
            else:
                self.install(persisted if persisted is not None else auth_spec)
        except Exception as exc:  # noqa: BLE001 - E-7: deploy never raises on HistoryStore content
            if persisted is None and history is None:
                raise  # the deploy-time spec itself is bad: a caller error, not history content
            self.auth_fault = f"{type(exc).__name__}: {exc}"
            self.install(auth_spec, persist=False)  # boot the deploy-time base; never overwrite the tampered record
        if not self.ledger.volatile:
            try:
                self.recovered = self.ledger.recover(self.world_digest())  # resolve a request left in doubt by a crash
            except Exception as exc:  # noqa: BLE001 - E-7
                if history is None:
                    raise
                self.auth_fault = self.auth_fault or f"ledger recovery: {type(exc).__name__}: {exc}"
        self.g3_init(governance)  # governance in force: deploy-time document, then the set_governance marks (PROT-H25 R25-7)

    # ---- authority --------------------------------------------------------------------------
    def install(self, auth_spec: dict, persist: bool = True) -> None:
        validate_strict(auth_spec, self.ops_spec)  # R-4: shared strict control, before anything changes (ValueError)
        doc = copy.deepcopy(auth_spec)
        self.booted = boot(self.domain, self.ops_spec, doc, self.handle, self._svc, self.clock.now,
                           lambda: self.hook("before_commit"))
        self.auth = doc
        if persist:
            self.persist(self.auth)
        self.eng = self.booted.engine
        if {"backstop_bypass", "mutable_gated_input"} & set(self.mutants):
            self.eng.register_principal(BYPASS)  # exists ONLY in mutated deployments
        self.delegations = delegation_table(self.auth)
        self.delegator = {p["id"]: p["delegated_by"] for p in self.auth["principals"]}

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
        on_behalf_of must be absent or P. A principal WITHOUT a delegator that names on_behalf_of Q is an EDGE request
        (PROT-H24 s3): the rules run with actor_for_rules = Q and the path is checked at the commit point (`edge_check`)."""
        p = self.booted.principals.get(sub)
        if p is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "unknown principal"})
        eff = self.delegator.get(sub)
        if eff is None and obo is not None:
            q = self.booted.principals.get(obo) if isinstance(obo, str) else None
            if q is None or obo == sub:
                return CallResult("DENIED", {"gate": "delegation", "reason": "no_valid_path"})
            return q
        if obo is not None and obo != eff:
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

    def run(self, sub: str, obo: Any, op: str, args: Any, rid: Any, via: str, gov=None) -> CallResult:
        if op not in self.ops:
            return CallResult("UNKNOWN", {"reason": "unknown operation"})
        if self.auth_fault is not None:  # E-7: the authority history is unresolved - nothing mutates
            return CallResult("UNAVAILABLE", {"reason": "authority_history_unresolved"})
        kind = "direct" if via == "direct" else "call_tool"
        late = getattr(gov, "late_schema", False)  # emergency act: PROT-H25 s3.5 puts the operation's own schema AFTER the procedure
        clean = self.check_shape(op, args, rid) if not late else json.loads(json.dumps(args))
        if isinstance(clean, CallResult):
            return clean
        if not late and self.schema_problem(op, clean) is not None:  # PROT-H26 s3.2: token -> schema (E-9) -> authority -> existence/rules
            return CallResult("INVALID", {"gate": "inputs", "reason": "schema"})
        who = self.principal(sub, obo, op)
        if isinstance(who, CallResult):
            if gov is None:
                return self.refuse(sub, obo, op, args, rid, who, kind) if who.body.get("gate") == "delegation" else who
            who = None  # constitutional execute/act: the procedural gates (and base authority) are decided in the transaction
        edge = obo is not None and self.delegator.get(sub) is None
        afp = fingerprint(sub, obo, op, clean)  # approval binding: on_behalf_of EXACTLY as supplied (P10; null != explicit delegator)
        obo_id = obo if edge else self.delegator.get(sub)  # request-id replay identity: the delegator (or edge root) in force
        bypass = via == "direct" and "backstop_bypass" in self.mutants
        fp = fingerprint(sub, obo_id, op, clean)
        with self._guard(), contextlib.ExitStack() as _mx:
            led = self.ledger.get(rid)
            if led is not None:
                if led["state"] != "COMMITTED":
                    return CallResult("UNAVAILABLE", {"reason": "request in flight"})
                return self._replay(led, who, bypass, fp, sub, obo_id, op, clean, rid, edge)
            if "unsynchronized_commit" in self.mutants:  # MUTANT ONLY: hold the unlocked check->commit window open (deterministic race)
                time.sleep(0.15)
                _mx.enter_context(self._mutant_io)  # the storage layer is serialised; the CHECK above is still stale
            g = self.guard_history(rid)  # R27-5: an anchored committed decision without its idempotency record never re-commits
            if g is not None:
                return g
            self._attempts += 1  # the Engine's own idempotency map is per attempt; request-id idempotency is the ledger's job
            attempt = self._attempts
            self.ledger.put_meta("attempts", attempt)
            self.ledger.prepare(rid, fp, self.world_digest(), sub, obo_id, op)  # durable BEFORE any world write
            d = self.new_decision(kind, sub, obo, op, clean, rid)
            try:
                res = self._commit(BYPASS if bypass else who, op, clean, f"{rid}~{attempt}", afp, rid, True, (sub, obo) if edge else None, d, gov)
                if res.status == "OK":
                    self.hook("after_commit")  # crash here: world committed, ledger still PREPARED (recovered at restart)
                res = self._anchor(d, res, rid)
                if d.get("committed"):  # the world holds the effect: the request id is spent even if the anchor failed
                    self.ledger.finalize(rid, fp, sub, obo_id, op, res.status, plain(res.body))
                else:
                    self.ledger.abort(rid)
                if res.status == "OK" and self._deferred:
                    self.flush_deferred()
            except Crash:
                raise
            except BaseException:
                self.ledger.abort(rid)
                raise
            return res

    def _anchor(self, d: dict, res: CallResult, rid: str) -> CallResult:
        """Anchor-before-ack (R27-6): the decision's root is appended to the anchor before any result leaves the core."""
        if self.prov is None:
            return res
        out = self.finish(d, res)
        cr = self.ledger.claimed_record(rid) if out.status == "OK" else None
        if cr and cr.get("decision_id"):  # the approval is spent in the anchor too: a restored record cannot be used twice
            from r3_shared.anchor import AnchorError  # noqa: PLC0415
            try:
                self.prov.mark_consumed(cr["decision_id"], rid)
            except AnchorError:
                return CallResult("UNAVAILABLE", {"reason": "anchor_unavailable"})
        return out

    def _replay(self, led, who, bypass, fp, sub, obo, op, clean, rid, edge=False) -> CallResult:
        if led["fp"] == fp:  # R5: same request -> never a second effect, decided against the authority in force NOW
            if led["status"] == "OK" and led["body"] == {"recovered": True} and self.prov is not None:
                return CallResult("UNAVAILABLE", {"reason": "unanchored_after_crash"})  # never an OK without its anchor entry
            if not edge and not bypass and not self.allowed_now(who, op, clean):  # edge requests: the stored result (PROT-H24 s4 retry)
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
        spec = self.eng.model.get("actions", op)
        who = self.booted.principals[approver]
        return any(self.pre_authority(who, op, args, capability=cap) for cap in pipeline.approval_capabilities(self.eng, spec))

    def _commit(self, who: Principal, op: str, args: dict, key: str, fp: str, rid: str, journaled: bool = True,
                edge: tuple | None = None, d: dict | None = None, gov=None) -> CallResult:
        """Propose; if the Engine parks it for approval, consume a matching single-use pre-approval and let the Engine's
        approval gate run in the same world transaction; without one the request is refused (zero effects).
        ONE world write transaction per commit (PROT-H24 s4): the edge path, the evidence read, the Engine pipeline, the
        adapters' writes and the `commit` mark share it; `tx.tick` is the commit tick."""
        d = d if d is not None else self.new_decision("direct", None, None, op, args, rid)
        th = self.handle(self.owner[op])  # the handle that owns the operation's effects (service, or its one external system)
        try:
            with th.transaction(tag="effect") as tx:
                self.eng.store.current = state_from_world(self.eng.model, self._svc)
                d["doc"] = self.auth
                if gov is not None:  # constitutional execute/act (PROT-H25 s3.4/3.5): procedure, then base authority, in this tx
                    who = gov.before(tx, d)
                else:
                    if edge is not None:  # freshness at the commit point: path validity is decided inside this transaction
                        bad = self.edge_check(edge[0], edge[1], op, args, tx.tick, d)
                        if bad is not None:
                            raise _Rollback(bad)
                    if "existence_status_split" in self.mutants and any(
                            self._svc.get(t, k) is None for t, k in self.refs_of(op, args)):   # MUTANT: existence is answered before authority
                        raise _Rollback(CallResult("INVALID", {"gate": "inputs", "reason": "inputs gate refused: not found"}))
                    if who is not BYPASS:
                        if not self.pre_authority(who, op, args):  # authority is world-independent and precedes existence (H26 3.2)
                            raise _Rollback(CallResult("DENIED", {"gate": "authority", "reason": "authority gate refused"}))
                        if self.case_required(edge[0] if edge else who.pid, op, args):
                            d["reason"] = "case_required"
                            raise _Rollback(CallResult("DENIED", {"gate": "governance", "reason": "case_required"}))
                d["evidence"] = self.evidence_for(op, args)
                rec = self.eng.propose(op, args, who, idempotency_key=key)
                if rec["state"] == "PENDING_APPROVAL":
                    approver = self.ledger.claim_approval(fp, rid, self._approval_check(op, args))  # durable claim: one approval, one commit
                    if approver is None:
                        raise _Rollback(CallResult("DENIED", {"gate": "approval", "reason": "approval_required"}))
                    rec = self.eng.approve(rec["exec"], self.booted.principals[approver])
                res = self.map_record(rec)
                if res.status != "OK":
                    raise _Rollback(res)  # nothing but an OK commit may touch the world (R7)
                if gov is not None:
                    gov.after(tx, res)  # the one `governance` mark of this transaction
                seq = tx.mark("commit", {"request_id": d["rid"], "kind": d["kind"], "authority_version": self.version()})
                d.update(world_seq=seq, tick=tx.tick, rows=tx_rows(th, tx.id))
            d["committed"] = True
            if gov is not None:
                gov.post(tx)
            self.ledger.put_meta(f"used:{d['rid']}", {"authority_version": self.version(), "world_seq": d["world_seq"],
                                                      "tick": d["tick"], "path": d["path"], "on_behalf_of": d["obo"]})
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

    def _approval_check(self, op: str, args: dict):
        """R27-5: with an anchor, a stored approval counts only if its decision is anchored with a provable envelope that
        names the same approver, operation and args, and the anchor does not show it consumed."""
        if self.prov is None:
            return None

        def verify(rec: dict) -> bool:
            did = rec.get("decision_id") or ""
            try:
                a = self.prov.anchored_decision(did)
                return bool(a and a["status"] == "OK" and a["kind"] == "approve" and a["subject"] == rec.get("approver")
                            and a["operation"] == op and a["args_digest"] == evid.digest(canonical_bytes(args))
                            and not self.prov.consumed(did))
            except (AnchorError, LookupError):
                return False
        return verify

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
