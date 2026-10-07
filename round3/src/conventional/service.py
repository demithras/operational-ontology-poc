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
from .policy import PolicyEngine
from .validation import RequestInvalid, validate_inputs
from .worldview import WorldView

WRITER = "conventional-service"
IDENTITY_FIELDS = ("principal", "actor", "owner", "requested_by", "subject", "sub", "user")


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


class Service:
    def __init__(self, domain: str, factory: Callable, verifier, ops_spec: dict, auth_spec: dict, clock,
                 audience: str = "conventional", mutant_switches: frozenset[str] = frozenset()):
        self.domain, self._factory, self._verifier, self._clock, self.audience = domain, factory, verifier, clock, audience
        self._spec = copy.deepcopy(ops_spec)
        self._ops = {o["name"]: o for o in self._spec["operations"]}
        self._link_types = {x["name"]: x for x in self._spec["link_types"]}
        self._helpers = {"manufacturing": MFG, "project": PROJ}[domain]
        self._mutants = shared_mutants.validate(mutant_switches)
        validate_strict(auth_spec, self._spec)  # R-4: invalid authority spec -> ValueError, nothing deployed
        self._policy = PolicyEngine(auth_spec, 1)
        self._lock = threading.RLock()
        self.unavailable: set[str] = set()
        self.crashed = False
        self._armed: str | None = None
        self._mem_ledger: dict = {}  # used ONLY by the ledger_after_commit_volatile mutant
        h = factory(WRITER)
        try:
            store.init(h)
            with h.transaction():
                store.authority_put(h, 1, auth_spec)
        finally:
            h.close()

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
                version, spec = store.authority_get(h)
            finally:
                h.close()
            self._policy = PolicyEngine(spec, version)
            self._mem_ledger, self.unavailable = {}, set()
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

    def set_authority(self, auth_spec: dict) -> int:
        validate_strict(auth_spec, self._spec)  # R-4: raise before anything changes
        with self._lock:
            if self.crashed:
                raise RuntimeError("deployment is crashed; restart() first")
            version = self._policy.version + 1
            h = self._factory(WRITER)
            try:
                with h.transaction():
                    store.authority_put(h, version, auth_spec)  # durable first, then swapped in
            finally:
                h.close()
            self._policy = PolicyEngine(auth_spec, version)
            return version

    @property
    def policy(self) -> PolicyEngine:
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
                request_id: str | None = None, *, _enforce: bool = True) -> CallResult:
        with self._guarded():
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            try:
                return self._execute(token, operation, args, on_behalf_of, request_id, _enforce)
            except _Abort as a:
                return a.result
            except (sqlite3.Error, ConnectionError) as exc:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable", "detail": type(exc).__name__})

    def _execute(self, token, operation, args, obo, request_id, enforce) -> CallResult:
        sub = self.authenticate(token)
        if sub is None:
            raise _Abort("DENIED", {"reason": "invalid_token"})
        if self.mutant("identity_substitution") and isinstance(args, dict):  # BUG: an args field selects the subject
            for f in IDENTITY_FIELDS:
                if isinstance(args.get(f), str):
                    sub, args = args[f], {k: v for k, v in args.items() if k != f}
                    break
        op = self._ops.get(operation) if isinstance(operation, str) else None
        if op is None:
            raise _Abort("INVALID", {"reason": "unknown_operation"})
        if enforce and not self._policy.exposed_operations(sub, [operation]):  # coarse gate before parsing details
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
        res = tuple((model.RESOURCES[n], v) for n, v in inputs.items() if n in model.RESOURCES)
        bound = BoundRequest(sub, obo, operation, MappingProxyType(inputs), res, request_id, self._policy.version,
                             store.fingerprint(sub, obo, operation, inputs))  # on_behalf_of bound LITERALLY (P10)
        h = self._factory(WRITER)
        try:
            # unsynchronized_commit BUG: no lock above and no world transaction here, so check-then-act interleaves
            with (contextlib.nullcontext() if self.mutant("unsynchronized_commit") else h.transaction()):
                result = self._txn(h, op, model, bound, args, enforce)
            fresh = result.status == "OK" and not result.body.get("replayed")
            if fresh and self._armed == "after_commit":  # world + durable ledger committed; the reply is lost
                raise self._crash_now()
            if fresh and self.mutant("ledger_after_commit_volatile") and bound.request_id is not None:
                # BUG: the committed-request record lives in memory and is written only after acknowledging
                self._mem_ledger[bound.request_id] = (bound.fingerprint, {"status": "OK", "body": result.body})
            return result
        finally:
            h.close()

    def _txn(self, h, op: dict, model, b: BoundRequest, raw_args, enforce: bool) -> CallResult:
        if enforce:
            d = self._policy.decide(b.subject, b.on_behalf_of, b.operation, list(b.resources))
            if not d.allowed or d.authority_version != self._policy.version:
                raise _Abort("DENIED", {"reason": d.reason})
        if b.request_id is not None:
            prior = self._mem_ledger.get(b.request_id) if self.mutant("ledger_after_commit_volatile") \
                else store.idem_get(h, b.request_id)
            if prior is not None:
                if prior[0] != b.fingerprint:
                    raise _Abort("INVALID", {"reason": "idempotency_key_reuse"})
                return CallResult(prior[1]["status"], {**prior[1]["body"], "replayed": True})
        inputs = dict(b.inputs)
        if self.mutant("mutable_gated_input"):  # BUG: commit re-reads the caller's (mutable) args after authorization
            try:
                inputs = model.from_args(raw_args).inputs()
            except RequestInvalid as exc:
                raise _Abort("INVALID", {"reason": exc.reason}) from exc
        actor = self._policy.effective_principal(b.subject)  # delegate -> its delegator, with or without on_behalf_of
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
            if needs_approval:
                self._consume_approval(h, op, b, needs_approval)
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
        if b.request_id is not None and not self.mutant("ledger_after_commit_volatile"):
            # request_id=None is accepted but has NO replay protection (documented, PROT-H23-A8 audit item b)
            store.idem_put(h, b.request_id, b.fingerprint, {"status": "OK", "body": body})
        return CallResult("OK", body)

    def _consume_approval(self, h, op: dict, b: BoundRequest, rule: str) -> None:
        aop = (op["approval"] or {}).get("approver_operation")
        for aid, approver in store.approvals_open(h, b.fingerprint):
            if aop and self._policy.can_approve(approver, b.subject, b.on_behalf_of, aop, list(b.resources)):
                store.approval_consume(h, aid)
                return
        raise _Abort("DENIED", {"reason": "approval_required", "rule": rule})

    # -- approvals -----------------------------------------------------------------------------
    def approve(self, token: str, operation: str, args: dict, requester: str, on_behalf_of: str | None = None) -> CallResult:
        """An approver binds an approval to the EXACT pending inputs; any change needs a fresh approval."""
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            try:
                approver = self.authenticate(token)
                op = self._ops.get(operation) if isinstance(operation, str) else None
                if approver is None:
                    raise _Abort("DENIED", {"reason": "invalid_token"})
                if op is None or not op["approval"]:
                    raise _Abort("INVALID", {"reason": "operation_takes_no_approval"})
                model = OPERATION_MODELS[operation]
                try:
                    inputs = model.from_args(args).inputs()
                except RequestInvalid as exc:
                    raise _Abort("INVALID", {"reason": exc.reason}) from exc
                res = [(model.RESOURCES[n], v) for n, v in inputs.items() if n in model.RESOURCES]
                if not self._policy.can_approve(approver, requester, on_behalf_of, op["approval"]["approver_operation"], res):
                    raise _Abort("DENIED", {"reason": "approver_not_permitted"})
                h = self._factory(WRITER)
                try:
                    with h.transaction():
                        if self._armed == "before_commit":
                            raise self._crash_now()
                        store.approval_add(h, store.fingerprint(requester, on_behalf_of, operation, inputs), approver)
                finally:
                    h.close()
                if self._armed == "after_commit":
                    raise self._crash_now()
                return CallResult("OK", {"approved_by": approver})
            except _Abort as a:
                return a.result
            except sqlite3.Error:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})

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
