"""Service layer: authenticate -> bind -> authorize (PDP) -> commit-time checks -> effects, in ONE world transaction.

Every entry point (execute / read / approve) authorizes server-side; the agent tool surface (tools.py) is only a
convenience layer above this API. Errors never leave partial effects: any non-OK outcome raises _Abort inside the
transaction, which rolls back (world effects AND idempotency/approval rows).
"""
from __future__ import annotations

import contextlib
import copy
import sqlite3
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable

from r3_shared.authspec import validate_strict
from r3_shared.identity import TokenError
from r3_shared.variant import CallResult

from r3_shared import mutants as shared_mutants

from . import effects, store
from .helpers_mfg import HELPERS as MFG
from .helpers_proj import HELPERS as PROJ, ID_READS
from .interp import Ctx, HelperError, ev
from .models_gen import OPERATION_MODELS
from .authority_ops import AuthorityOps
from .histledger import HistLedger, LedgerUnresolved
from .pdp import Pdp
from .provenance import DecisionCtx, Provenance, has_float
from .replay import Replayer
from .validation import RequestInvalid, validate_inputs
from .worldview import WorldView

WRITER = "conventional-service"
IDENTITY_FIELDS = ("principal", "actor", "owner", "requested_by", "subject", "sub", "user")


def _base(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("spec", "capabilities", "revoked", "max_delegation_depth")}


_LINEAGE_ERRORS = (LedgerUnresolved, ValueError, KeyError, TypeError, AttributeError, IndexError)


class _Abort(Exception):
    def __init__(self, status: str, body: dict):
        super().__init__(status)
        self.result = CallResult(status, body)


@dataclass(frozen=True)
class BoundRequest:
    """The authorized request. Frozen: nothing the caller holds can alter what commits (R4)."""
    subject: str
    on_behalf_of: str | None
    operation: str
    inputs: MappingProxyType
    resources: tuple[tuple[str, str], ...]
    request_id: str | None
    authority_version: int
    fingerprint: str


class Service(AuthorityOps):
    def __init__(self, domain: str, factory: Callable, verifier, ops_spec: dict, auth_spec: dict, clock,
                 audience: str = "conventional", mutant_switches: frozenset[str] = frozenset(),
                 history=None, anchor=None):
        self.domain, self._factory, self._verifier, self._clock, self.audience = domain, factory, verifier, clock, audience
        self._spec = copy.deepcopy(ops_spec)
        self._ops = {o["name"]: o for o in self._spec["operations"]}
        self._link_types = {x["name"]: x for x in self._spec["link_types"]}
        self._helpers = {"manufacturing": MFG, "project": PROJ}[domain]
        self._mutants = shared_mutants.validate(mutant_switches)
        validate_strict(auth_spec, self._spec)  # R-4: invalid authority spec -> ValueError, nothing deployed
        self.history, self.anchor = history, anchor
        self._store = HistLedger(history) if history is not None else store.AuxStore()
        self._pending: list = []  # revoke_commit_reorder mutant only
        self._dcache: dict = {}  # PDP decision cache (stale_authority_cache mutant lives here)
        self._lock = threading.RLock()
        self.unavailable: set[str] = set()
        self.crashed = False
        self._armed: str | None = None
        self._mem_ledger: dict = {}  # used ONLY by the ledger_after_commit_volatile mutant
        doc, version = auth_spec, 1
        self._initial_spec = copy.deepcopy(auth_spec)
        self._authority_unresolved: str | None = None  # E-7: set when the durable authority lineage cannot be trusted
        h = factory(WRITER)
        try:
            self._store.init(h)
            try:
                got = None
                if history is not None:  # a fresh deployment over an existing history continues its authority lineage
                    got = self._store.authority_get(h)
                    if got is not None and _base(got[1]) == _base(auth_spec):
                        version, doc = got
                        Pdp(doc, version, self._mutants)  # a document that cannot even be evaluated is unresolved too
                with h.transaction():
                    if version == 1 and (history is None or got is None):
                        self._store.authority_put(h, 1, doc)
            except _LINEAGE_ERRORS as exc:  # E-7: never raise from deploy because of HistoryStore content
                self._authority_unresolved = f"{type(exc).__name__}"
                doc, version = auth_spec, 1
        finally:
            h.close()
        self._policy = Pdp(doc, version, self._mutants)
        self.stream = self._init_stream(domain)
        self.prov = Provenance(history, anchor, self.stream, self._spec, clock, self._mutants) \
            if history is not None and anchor is not None else None
        self.replayer = Replayer(self)

    def _init_stream(self, domain: str) -> str | None:
        if self.history is None:
            return None
        raw = self.history.get("meta/stream")
        if raw is None:
            import random
            rng = random.Random(f"conventional|{domain}|{getattr(self.history, '_path', '')}")
            raw = f"conventional-{domain}-{rng.getrandbits(128):032x}".encode()
            self.history.put("meta/stream", raw)
        return raw.decode()

    def current_artifact(self, kind: str, operation: str = ""):
        """The CURRENT (not historical) artifact bytes: used only by the fallback_to_current mutant."""
        from r3_shared.authgraph import authority_document
        from r3_shared.evidence import canonical_bytes
        if kind == "authority":
            return canonical_bytes(authority_document(self._policy.doc))
        if kind in ("policy", "contract") and self.prov is not None:
            op = self._ops.get(operation)  # delegate/revoke bind `null`: no operation definition
            return self.prov.policy_bytes(op) if kind == "policy" else self.prov.contract_bytes(op)
        return None

    # -- crash / restart (PROT-H23-A8). Durable state = world DB (effects, idempotency ledger, approvals, authority). --
    def arm_crash(self, point: str) -> None:
        if point not in ("before_commit", "after_commit"):
            raise ValueError(f"bad crash point {point!r}")
        with self._lock:
            self._armed = point

    def crash(self) -> None:
        with self._lock:
            self.crashed, self._armed = True, None
            self._mem_ledger = {}
            self._policy = None  # in-memory policy is lost

    def restart(self) -> None:
        with self._lock:
            h = self._factory(WRITER)
            try:
                got = self._store.authority_get(h)
                if got is None:
                    raise LedgerUnresolved("no durable authority version")
                version, spec = got
                self._policy = Pdp(spec, version, self._mutants)
                self._authority_unresolved = None
            except _LINEAGE_ERRORS as exc:  # E-7: restart over a damaged lineage stays up but refuses mutations
                self._authority_unresolved = f"{type(exc).__name__}"
                self._policy = Pdp(self._initial_spec, 1, self._mutants)
            finally:
                h.close()
            self._mem_ledger, self.unavailable, self._pending, self._dcache = {}, set(), [], {}
            self.crashed, self._armed = False, None

    def _crash_now(self) -> _Abort:
        self.crashed, self._armed, self._mem_ledger = True, None, {}
        return _Abort("UNKNOWN", {"reason": "crashed"})

    def _guarded(self):
        """The lock that serialises the authorize->commit section; the unsynchronized_commit mutant has none."""
        return contextlib.nullcontext() if self.mutant("unsynchronized_commit") else self._lock

    # -- configuration -------------------------------------------------------------------------
    def mutant(self, name: str) -> bool:
        return name in self._mutants

    @property
    def mutants(self):
        return self._mutants

    @property
    def factory(self):
        return self._factory

    @property
    def policy(self) -> Pdp:
        return self._policy

    @property
    def operations(self) -> list[str]:
        return list(self._ops)

    def authenticate(self, token: str) -> str | None:
        try:
            return self._verifier.verify(token, self.audience, self._clock)
        except TokenError:
            return None

    # -- context -------------------------------------------------------------------------------
    def _ctx(self, h, inputs: dict, resources: dict, actor: str) -> Ctx:
        view = WorldView.load(h, self._spec, self._clock.now())
        return Ctx(view, self._spec["config"], self._link_types, resources, dict(inputs), self._helpers,
                   lambda t, k, r: self._policy.holds(actor, t, k, r),
                   tuple(rt["name"] for rt in self._spec["resource_types"]),
                   ID_READS if self.domain == "project" else {})

    # -- the write path ------------------------------------------------------------------------
    def execute(self, token: str, operation: str, args: dict, on_behalf_of: str | None = None,
                request_id: str | None = None, *, _enforce: bool = True, _kind: str = "direct",
                _hidden: bool = False) -> CallResult:
        with self._guarded():
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._authority_unresolved:  # E-7: the authority a decision depends on cannot be trusted: no effects
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            dc = DecisionCtx(_kind, request_id if isinstance(request_id, str) and request_id.strip() else None, None,
                             on_behalf_of if isinstance(on_behalf_of, str) else None, operation, args)
            try:
                res = self._execute(token, operation, args, on_behalf_of, request_id, _enforce, dc, _hidden)
            except _Abort as a:
                res = a.result
            except (sqlite3.Error, ConnectionError) as exc:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable", "detail": type(exc).__name__})
            except LedgerUnresolved:
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            return self._provenance(dc, res)

    def _schema_valid(self, dc: DecisionCtx) -> bool:
        """E-8: schema validity from the ops-spec input schema (never from a reason string)."""
        model = OPERATION_MODELS.get(dc.operation) if isinstance(dc.operation, str) else None
        if dc.op is None or model is None or dc.subject is None or has_float(dc.args):
            return False
        if dc.obo is not None and not isinstance(dc.obo, str):
            return False
        try:
            model.from_args(dc.args)
        except RequestInvalid:
            return False
        return True

    def _provenance(self, dc: DecisionCtx, res: CallResult) -> CallResult:
        """Anchor-before-ack: the governed decision's envelope root is appended to the anchor before `res` is returned."""
        if self.prov is None or res.status not in ("OK", "DENIED", "INVALID") or self.crashed \
                or dc.extra.get("replayed"):
            return res
        if dc.kind in ("call_tool", "direct"):  # E-8: governed iff the request is schema-valid, whatever the status
            dc.governed = self._schema_valid(dc)
        if not dc.governed:
            return res
        h = self._factory(WRITER)
        try:
            if dc.evidence is None:  # refused before the commit transaction read it: bind the objects as they are now
                model = OPERATION_MODELS.get(dc.operation)
                try:
                    ins = model.from_args(dc.args).inputs() if model else {}
                except RequestInvalid:
                    ins = {}
                dc.evidence = self.prov.collect(h, dc.op, model.RESOURCES, ins) if dc.op and model else []
            dc.authority_doc = dc.authority_doc or self._policy.doc
            return self.prov.finalize(h, dc, res)
        finally:
            h.close()

    def _execute(self, token, operation, args, obo, request_id, enforce, dc: DecisionCtx, hidden=False) -> CallResult:
        sub = self.authenticate(token)
        if sub is None:
            raise _Abort("DENIED", {"reason": "invalid_token"})
        if self.mutant("identity_substitution") and isinstance(args, dict):  # BUG: an args field selects the subject
            for f in IDENTITY_FIELDS:
                if isinstance(args.get(f), str):
                    sub, args = args[f], {k: v for k, v in args.items() if k != f}
                    break
        dc.subject = sub
        op = self._ops.get(operation) if isinstance(operation, str) else None
        if hidden:  # the tool layer found no such tool for this subject: a governed refusal (E-8), decided server-side
            dc.op = op
            raise _Abort("DENIED", {"reason": "tool_not_available"})
        if op is None:
            raise _Abort("INVALID", {"reason": "unknown_operation"})
        dc.op = op
        if enforce and not self._policy.exposed_operations(sub, [operation]):  # coarse gate before parsing details
            dc.governed = True
            raise _Abort("DENIED", {"reason": "no_matching_allow"})
        if obo is not None and not isinstance(obo, str):
            raise _Abort("INVALID", {"reason": "bad_on_behalf_of"})
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
            raise _Abort("INVALID", {"reason": "bad_request_id"})
        model = OPERATION_MODELS[operation]
        try:
            inputs = model.from_args(args).inputs()
        except RequestInvalid as exc:
            raise _Abort("INVALID", {"reason": exc.reason, "detail": exc.detail}) from exc
        if self.prov is not None and has_float(inputs):  # PROT-H27 s3: no floats in bound artifacts
            raise _Abort("INVALID", {"reason": "float_in_artifact"})
        res = tuple((model.RESOURCES[n], v) for n, v in inputs.items() if n in model.RESOURCES)
        bound = BoundRequest(sub, obo, operation, MappingProxyType(inputs), res, request_id, self._policy.version,
                             store.fingerprint(sub, obo, operation, inputs))  # on_behalf_of bound LITERALLY (P10)
        # E-4: dc.args stays the args exactly as passed (args_digest covers them, not the normalised inputs)
        h = self._factory(WRITER)
        try:
            # unsynchronized_commit BUG: no lock above and no world transaction here, so check-then-act interleaves
            with (contextlib.nullcontext() if self.mutant("unsynchronized_commit") else h.transaction(tag="effect")) as tx:
                result = self._txn(h, tx, op, model, bound, args, enforce, dc)
            fresh = result.status == "OK" and not result.body.get("replayed")
            if fresh and self._pending:  # revoke_commit_reorder BUG: acknowledged revocations apply after this commit
                self._drain_pending()
            if fresh and self._armed == "after_commit":  # world + durable ledger committed; the reply is lost
                raise self._crash_now()
            if fresh and self.mutant("ledger_after_commit_volatile") and bound.request_id is not None:
                # BUG: the committed-request record lives in memory and is written only after acknowledging
                self._mem_ledger[bound.request_id] = (bound.fingerprint, {"status": "OK", "body": result.body})
            if result.body.get("replayed"):
                dc.governed = False  # a retry of a committed request is not a new decision (its envelope exists)
                dc.extra["replayed"] = True
            return result
        finally:
            h.close()

    def _decide(self, b: BoundRequest, tick: int):
        """PDP decision. The cache key includes the authority digest and the commit tick (always fresh); the
        stale_authority_cache mutant keys on (subject, obo, op, resources) only and never invalidates."""
        pol = self._policy
        key = (b.subject, b.on_behalf_of, b.operation, b.resources) if self.mutant("stale_authority_cache") \
            else (pol.version, pol.digest, b.subject, b.on_behalf_of, b.operation, b.resources, tick)
        d = self._dcache.get(key)
        if d is None:
            d = self._dcache[key] = pol.decide(b.subject, b.on_behalf_of, b.operation, list(b.resources), tick)
        return d

    def _txn(self, h, tx, op: dict, model, b: BoundRequest, raw_args, enforce: bool, dc: DecisionCtx) -> CallResult:
        tick = tx.tick if tx is not None else self._clock.now()
        dc.authority_doc, dc.governed = self._policy.doc, True
        if self.prov is not None:
            dc.evidence = self.prov.collect(h, op, model.RESOURCES, dict(b.inputs))
        path: tuple = ()
        if enforce:
            d = self._decide(b, tick)
            stale = self.mutant("stale_authority_cache")  # BUG: the cached decision's version is never compared
            if not d.allowed or (not stale and d.authority_version != self._policy.version):
                raise _Abort("DENIED", {"reason": d.reason})
            path = d.path
        dc.path = path
        if b.request_id is not None:
            prior = self._mem_ledger.get(b.request_id) if self.mutant("ledger_after_commit_volatile") \
                else self._store.idem_get(h, b.request_id)
            if prior is not None:
                dc.governed, dc.extra["replayed"] = False, True
                if prior[0] != b.fingerprint:
                    raise _Abort("INVALID", {"reason": "idempotency_key_reuse"})
                if self.prov is not None and not self.prov.anchored(b.request_id):
                    raise _Abort("UNAVAILABLE", {"reason": "anchor_unavailable"})
                return CallResult(prior[1]["status"], {**prior[1]["body"], "replayed": True})
        inputs = dict(b.inputs)
        if self.mutant("mutable_gated_input"):  # BUG: commit re-reads the caller's (mutable) args after authorization
            try:
                inputs = model.from_args(raw_args).inputs()
            except RequestInvalid as exc:
                raise _Abort("INVALID", {"reason": exc.reason}) from exc
        # edge request: rules see the root principal Q; a static delegate sees its delegator (H23)
        actor = b.on_behalf_of if path else self._policy.effective_principal(b.subject)
        try:
            ctx = self._ctx(h, inputs, model.RESOURCES, actor)
            for name, kind, required in model.SCHEMA:  # R-2: a supplied optional ref must resolve at commit
                if kind == "resource" and not required and name in inputs \
                        and ctx.view.props(model.RESOURCES[name], inputs[name]) is None:
                    raise _Abort("INVALID", {"reason": "target_not_found", "input": name})
            for p in op["preconditions"]:
                if not ev(p["predicate"], ctx):
                    raise _Abort("INVALID", {"reason": "precondition_failed", "rule": p["id"]})
            needs_approval = None
            for br in op["business_rules"]:
                if br["decision"] == "classify" or not ev(br["when"], ctx):
                    continue
                if br["decision"] == "deny":
                    raise _Abort("DENIED", {"reason": "business_rule", "rule": br["id"]})
                needs_approval = needs_approval or br["id"]
            for name, kind, required in model.SCHEMA:  # E-6: a supplied REQUIRED ref must resolve too (after the
                if kind == "resource" and required and name in inputs \
                        and ctx.view.props(model.RESOURCES[name], inputs[name]) is None:  # deny rules, as before)
                    raise _Abort("INVALID", {"reason": "target_not_found", "input": name})
            if needs_approval:
                self._consume_approval(h, tx, op, b, needs_approval)
            planned = effects.resolve(op["effects"], ctx)
        except HelperError as exc:
            raise _Abort("INVALID", {"reason": "helper_error", "detail": str(exc)}) from exc
        except effects.EffectRejected as exc:
            raise _Abort("INVALID", {"reason": "effect_rejected", "detail": str(exc)}) from exc
        if self._armed == "before_commit":  # authorized and validated, nothing written yet: the open transaction is lost
            raise self._crash_now()
        if self.mutant("unsynchronized_commit"):
            time.sleep(0.05)  # the unprotected window between the precondition read and the write
        try:
            n = effects.apply(h, planned, b.request_id, self.unavailable)
        except effects.EffectRejected as exc:
            raise _Abort("INVALID", {"reason": "effect_rejected", "detail": str(exc)}) from exc
        except ConnectionError as exc:
            raise _Abort("UNAVAILABLE", {"reason": "dependency_unavailable", "detail": str(exc)}) from exc
        body = {"operation": b.operation, "effects": n, "request_id": b.request_id, "authority_version": b.authority_version}
        if tx is not None:  # PROT-H24 s4: every effect transaction carries one `commit` mark (the commit point)
            dc.tx_id, dc.tick = tx.id, tx.tick
            dc.world_seq = tx.mark("commit", {"request_id": b.request_id, "kind": dc.kind,
                                              "authority_version": self._policy.digest})
        if b.request_id is not None and not self.mutant("ledger_after_commit_volatile"):
            # request_id=None is accepted but has NO replay protection (documented, PROT-H23-A8 audit item b)
            self._store.idem_put(h, b.request_id, b.fingerprint, {
                "status": "OK", "body": body,
                "used": {"authority_version": self._policy.digest, "path": list(path), "on_behalf_of": b.on_behalf_of}})
        return CallResult("OK", body)

    def _consume_approval(self, h, tx, op: dict, b: BoundRequest, rule: str) -> None:
        aop = (op["approval"] or {}).get("approver_operation")
        extra = self._policy.approval_forbidden(b.subject, b.on_behalf_of)
        for aid, approver in self._store.approvals_open(h, b.fingerprint):
            if aop and self._policy.can_approve(approver, b.subject, b.on_behalf_of, aop, list(b.resources), extra):
                self._store.approval_consume(h, aid, tx)
                return
        raise _Abort("DENIED", {"reason": "approval_required", "rule": rule})

    # -- approvals -----------------------------------------------------------------------------
    def approve(self, token: str, operation: str, args: dict, requester: str, on_behalf_of: str | None = None) -> CallResult:
        """An approver binds an approval to the EXACT pending inputs; any change needs a fresh approval."""
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._authority_unresolved:
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            dc = DecisionCtx("approve", None, None, on_behalf_of if isinstance(on_behalf_of, str) else None, operation, args)
            try:
                approver = self.authenticate(token)
                op = self._ops.get(operation) if isinstance(operation, str) else None
                if approver is None:
                    raise _Abort("DENIED", {"reason": "invalid_token"})
                dc.subject = approver
                if op is None or not op["approval"]:
                    raise _Abort("INVALID", {"reason": "operation_takes_no_approval"})
                dc.op = op
                model = OPERATION_MODELS[operation]
                try:
                    inputs = model.from_args(args).inputs()
                except RequestInvalid as exc:
                    raise _Abort("INVALID", {"reason": exc.reason}) from exc
                res = [(model.RESOURCES[n], v) for n, v in inputs.items() if n in model.RESOURCES]
                dc.governed, dc.authority_doc = True, self._policy.doc
                if not self._policy.can_approve(approver, requester, on_behalf_of, op["approval"]["approver_operation"], res,
                                                self._policy.approval_forbidden(requester, on_behalf_of)):
                    raise _Abort("DENIED", {"reason": "approver_not_permitted"})
                h = self._factory(WRITER)
                try:
                    with h.transaction(tag="approve") as tx:
                        if self._armed == "before_commit":
                            raise self._crash_now()
                        if self.prov is not None:
                            dc.evidence = self.prov.collect(h, op, model.RESOURCES, inputs)
                        self._store.approval_add(h, store.fingerprint(requester, on_behalf_of, operation, inputs), approver, tx)
                    dc.tx_id, dc.tick = tx.id, tx.tick
                finally:
                    h.close()
                if self._armed == "after_commit":
                    raise self._crash_now()
                res_ok = CallResult("OK", {"approved_by": approver})
            except _Abort as a:
                res_ok = a.result
            except (sqlite3.Error, LedgerUnresolved):
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})
            return self._provenance(dc, res_ok)

    # -- reads ---------------------------------------------------------------------------------
    def read(self, token: str, operation: str, args: dict) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self.authenticate(token)
            if sub is None or not self._policy.known(sub):
                return CallResult("DENIED", {"reason": "invalid_token" if sub is None else "unknown_principal"})
            try:
                h = self._factory(WRITER)
                try:
                    return self._read(h, operation, args)
                finally:
                    h.close()
            except sqlite3.Error:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})

    def _read(self, h, name: Any, args: Any) -> CallResult:
        if name == "get":
            try:
                a = validate_inputs((("type", "string", True), ("key", "string", True)), args)
            except RequestInvalid as exc:
                return CallResult("INVALID", {"reason": exc.reason})
            rec = h.get(a["type"], a["key"])
            return CallResult("OK", copy.deepcopy(rec)) if rec else CallResult("UNKNOWN", {})
        defs = {r["name"]: r for r in self._spec["reads"] + self._spec["helpers"]}
        if not isinstance(name, str) or name not in defs or name not in self._helpers:
            return CallResult("INVALID", {"reason": "unknown_read"})
        sch = tuple((i["name"], "resource" if i["type"] == "resource" else i["type"], bool(i["required"]))
                    for i in defs[name]["inputs"])
        res = {i["name"]: i["resource_type"] for i in defs[name]["inputs"] if i["type"] == "resource"}
        try:
            vals = validate_inputs(sch, args)
            ctx = self._ctx(h, vals, res, "")
            kw = {k: (res[k], v) if k in res else v for k, v in vals.items()}
            return CallResult("OK", {"value": copy.deepcopy(self._helpers[name](ctx, **kw))})
        except RequestInvalid as exc:
            return CallResult("INVALID", {"reason": exc.reason})
        except HelperError as exc:
            return CallResult("INVALID", {"reason": "helper_error", "detail": str(exc)})
