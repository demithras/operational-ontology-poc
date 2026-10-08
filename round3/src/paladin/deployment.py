"""PaladinDeployment: the r3_shared Deployment protocol over the Paladin core (+ approve / set_authority extras)."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading

from paladin import evid, replay as _replay
from paladin.authreplay import Reauth
from paladin.core import AUDIENCE, Core, Crash, fingerprint, plain
from paladin.engine import CapabilityError, InvalidRequest, Principal
from paladin.prov import HISTORY_LAYOUT, stream_for
from paladin.public import public
from paladin.surface import SurfaceFactory, UnknownTool, who_of
from paladin.worldbridge import state_from_world
from r3_shared.evidence import canonical_bytes
from r3_shared.governance import validate_governance
import functools

from r3_shared.variant import CallResult, ReplayResult, ToolDescriptor

_JSON = {"integer": "integer", "string": "string", "resource": "string", "json": None, "boolean": "boolean"}


def _schema(op: dict) -> dict:
    props = {}
    for i in op["inputs"]:
        t = _JSON.get(i["type"])
        props[i["name"]] = {"type": t} if t else {}
    return {"type": "object", "properties": props, "required": [i["name"] for i in op["inputs"] if i["required"]],
            "additionalProperties": False}


class PaladinDeployment:
    audience = AUDIENCE
    HISTORY_LAYOUT = {**HISTORY_LAYOUT, "authority_version": "auth/"}  # every durable record kind kept in the HistoryStore

    def __init__(self, domain, factory, verifier, ops_spec, auth_spec, clock, mutants=frozenset(), state_dir=None,
                 history=None, anchor=None, governance=None):
        if governance is not None:
            validate_governance(governance, auth_spec, ops_spec)   # a caller error: ValueError, nothing deployed
        self._governance = governance
        self._args = (domain, factory, verifier, ops_spec, auth_spec, clock, mutants)
        self.history, self.anchor, self.mutants = history, anchor, frozenset(mutants)
        self.stream = stream_for(history, anchor, domain) if history is not None else None
        self.reauth, self.ops_spec = Reauth(domain, ops_spec), ops_spec
        self._state_dir = None if history is not None else (state_dir or tempfile.mkdtemp(prefix="paladin-state-"))
        self._meta = threading.Lock()   # crash flags
        self._tl = threading.local()    # the armed crash point of THIS thread's request
        self._armed = None
        self._crashed = False
        self._auth_version = None
        self._build(restart=False)

    # ---- crash / restart (PROT-H23-A8) ------------------------------------------------------
    def _build(self, restart: bool) -> None:
        d, f, v, ops, auth, clk, mut = self._args
        self._c = Core(d, f, v, ops, auth, clk, mut, self._state_dir, self._fire, restart, self.history, self.anchor, self.stream, self._governance)
        self._surfaces = SurfaceFactory(self._c.booted.ir)
        self._auth_version = self._c.version()

    def _fire(self, point: str) -> None:
        if getattr(self._tl, "point", None) == point:
            self._tl.point = None
            raise Crash(point)

    def _die(self) -> None:
        """Process death: wait out in-flight work, then drop everything held in memory (world + state_dir survive)."""
        core = self._c
        if core is not None:
            with core.lock:
                with self._meta:
                    self._crashed, self._c = True, None

    _DOWN = CallResult("UNAVAILABLE", {"reason": "crashed"})

    def _mutating(self, fn, arms: bool = True):
        """Run one state-changing request. An armed crash fires only when the request REACHES its point; a request refused
        (or replayed) before the point returns its normal result and the arm stays pending for the next request."""
        with self._meta:
            if self._crashed:
                return self._DOWN
            point = self._armed if arms else None
            if point is not None:
                self._armed = None
        self._tl.point = point
        try:
            res = fn()
        except Crash:
            self._die()
            return CallResult("UNKNOWN", {"reason": "crashed"})
        finally:
            fired = self._tl.point is None
            self._tl.point = None
            if point is not None and not fired:
                with self._meta:
                    if self._armed is None:
                        self._armed = point  # not reached: keep the arm
        return res

    def arm_crash(self, point) -> None:
        if point not in ("before_commit", "after_commit"):
            raise ValueError(f"unknown crash point {point!r}")
        with self._meta:
            self._armed = point

    def crash(self) -> None:
        self._die()

    def restart(self) -> None:
        with self._meta:
            if not self._crashed:
                return
            self._armed = None
        self._build(restart=True)
        with self._meta:
            self._crashed = False

    # ---- authority management ---------------------------------------------------------------
    def set_authority(self, auth_spec: dict) -> None:
        c = self._c
        if c is None:
            raise RuntimeError("deployment is crashed; restart() first")
        with c.lock:
            c.replace_authority(auth_spec)  # one world transaction with the `authority` mark (PROT-H24 s4)
            self._surfaces = SurfaceFactory(c.booted.ir)
            self._auth_version = c.version()

    def authority_version(self) -> str:
        """sha256 hex of the canonical JSON of the spec in force (r3_shared protocol)."""
        return self._auth_version

    # ---- surface (R3) -----------------------------------------------------------------------
    def _surface(self, sub: str, obo, propose):
        c = self._c
        who = c.principal(sub, obo, None)
        if isinstance(who, CallResult):
            return who
        with c.lock:
            c.eng.store.current = state_from_world(c.eng.model, c._svc)
            types = sorted(c.eng.model.all("object_types"))
            return self._surfaces.surface(c.eng, who_of(who, None if who.delegated_by is None else who_of(who.delegated_by)),
                                          propose, types)

    def _exposed(self, sub: str, obo) -> set | CallResult:
        s = self._surface(sub, obo, lambda *_a: {})
        if isinstance(s, CallResult):
            return s
        ops = self._surfaces.granted_operations(s)
        eff = self._c.delegator.get(sub)
        if eff is not None:  # a delegate's surface only offers what its delegation lists
            ops &= set(self._c.delegations.get((sub, eff), ()))
        return ops

    def tools(self, token: str) -> list[ToolDescriptor]:
        if self._crashed:
            return []
        sub = self._c.subject(token)
        if sub is None or sub not in self._c.booted.principals:
            return []
        if "tool_overexposure" in self._c.mutants:  # MUTANT: every operation listed regardless of grants
            names = set(self._c.ops)
        else:
            names = set(self._exposed(sub, None))  # a delegate is always surfaced as its delegator's delegate
        with self._c.lock:  # P1e-5: descriptors use the frozen shared derivation verbatim (PROT-H26 3.4)
            return self._c.tool_descriptors(sub, names)

    # ---- calls ------------------------------------------------------------------------------
    def _pub(self, res: CallResult, rid, op=None, args=None) -> CallResult:
        leak = (lambda: self._c.leak_detail(op, args)) if "error_detail_leak" in self.mutants else None
        return public(res, rid, leak)

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None) -> CallResult:
        return self._mutating(lambda: self._pub(self._call_tool(token, name, args, on_behalf_of, request_id), request_id, name, args))

    def _call_tool(self, token, name, args, on_behalf_of, request_id) -> CallResult:
        sub = self._c.subject(token, args)
        if sub is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token"})
        if not isinstance(name, str) or name not in self._c.ops:
            return CallResult("UNKNOWN", {"reason": "no such tool"})
        if not isinstance(args, dict):
            return CallResult("INVALID", {"gate": "inputs", "reason": "args must be an object"})
        who = self._c.principal(sub, on_behalf_of, name)
        if isinstance(who, CallResult):
            return self._c.refuse(sub, on_behalf_of, name, args, request_id, who, "call_tool") \
                if who.body.get("gate") == "delegation" else who
        if "tool_overexposure" in self._c.mutants:
            return self._c.run(sub, on_behalf_of, name, args, request_id, "tool")
        box: dict = {}

        def propose(aid, inputs, key):  # the generated runtime hands the request to the core: the only commit path
            box["r"] = self._c.run(sub, on_behalf_of, aid, inputs, key, "tool")
            return {}

        surf = self._surface(sub, on_behalf_of, propose)
        if isinstance(surf, CallResult):
            return surf
        tool = self._surfaces.tool_of_op[name]
        if name not in self._surfaces.granted_operations(surf):
            return self._c.refuse(sub, on_behalf_of, name, args, request_id, CallResult(
                "DENIED", {"gate": "surface", "reason": "operation not granted to this principal"}), "call_tool")  # absent from its surface
        try:
            surf.call(tool, idempotency_key=request_id, **args)
        except UnknownTool:
            return CallResult("UNKNOWN", {"reason": "no such tool"})
        except TypeError as exc:
            return CallResult("INVALID", {"gate": "inputs", "reason": f"bad arguments: {exc}"})
        return box.get("r") or CallResult("INVALID", {"reason": "request was not issued"})

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None) -> CallResult:
        return self._mutating(lambda: self._pub(self._direct(token, operation, args, on_behalf_of, request_id), request_id, operation, args))

    def _direct(self, token, operation, args, on_behalf_of, request_id) -> CallResult:
        sub = self._c.subject(token, args)
        if sub is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token"})
        return self._c.run(sub, on_behalf_of, operation, args, request_id, "direct")

    def read(self, token, operation, args) -> CallResult:
        """P1e-5 / Q12: "get" -> read_object, "list" -> list_objects, otherwise query - every one over the low view."""
        if operation in ("get", "list") and isinstance(args, dict):
            if operation == "get":
                return self._low(token, lambda c, s: c.read_object(s, f"{args.get('type')}:{args.get('key')}"))
            return self._low(token, lambda c, s: c.list_objects(s, args.get("type")))
        return self._low(token, lambda c, s: c.query(s, operation, args))

    def _low(self, token, fn) -> CallResult:
        """One low-channel call: token -> subject -> answer from the subject's low view under the Core lock."""
        if self._crashed:
            return self._DOWN
        c = self._c
        sub = c.subject(token)
        if sub is None or sub not in c.booted.principals:
            return CallResult("DENIED", {"reason": "token"})
        with c.lock:
            return fn(c, sub)

    def read_object(self, token, ref) -> CallResult:
        return self._low(token, lambda c, s: c.read_object(s, ref))

    def list_objects(self, token, type_) -> CallResult:
        return self._low(token, lambda c, s: c.list_objects(s, type_))

    def list_links(self, token, ref, link_type) -> CallResult:
        return self._low(token, lambda c, s: c.list_links(s, ref, link_type))

    def query(self, token, name, args) -> CallResult:
        return self._low(token, lambda c, s: c.query(s, name, args))

    def subscribe(self, token, spec) -> CallResult:
        return self._low(token, lambda c, s: c.subscribe(s, spec))

    def poll(self, token, sub) -> CallResult:
        return self._low(token, lambda c, s: c.poll(s, sub))

    def prov_decision(self, token, decision_id) -> CallResult:
        return self._low(token, lambda c, s: c.prov_decision(s, decision_id))

    def prov_object(self, token, ref) -> CallResult:
        return self._low(token, lambda c, s: c.prov_object(s, ref))

    def authority_used_as(self, token, request_id) -> CallResult:
        return self._low(token, lambda c, s: c.authority_used_as(s, request_id))

    def _read(self, token, operation, args) -> CallResult:
        sub = self._c.subject(token)
        if sub is None or sub not in self._c.booted.principals:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token or unknown principal"})
        c = self._c
        c.eng.store.current = state_from_world(c.eng.model, c._svc)
        try:
            if operation in ("get", "list") and isinstance(args, dict):
                v = c.eng.get(args["type"], args["key"]) if operation == "get" else \
                    [r for r in c.eng.read_view().list(args["type"])]
                return CallResult("OK", {"value": plain(v)})
            if operation in c.reads and isinstance(args, dict):
                return CallResult("OK", {"value": plain(c.eng.call_function(operation, dict(args), principal=sub))})
        except (InvalidRequest, KeyError, TypeError, LookupError) as exc:
            return CallResult("INVALID", {"reason": f"{type(exc).__name__}: {exc}"})
        return CallResult("UNKNOWN", {"reason": "unknown read"})

    def approve(self, token, operation, args, requester, on_behalf_of=None) -> CallResult:
        # recording an approval commits nothing to the world: it never reaches a crash point and leaves an armed crash pending
        return self._mutating(lambda: self._pub(self._approve(token, operation, args, requester, on_behalf_of), None, operation, args), arms=False)

    def _approve(self, token, operation, args, requester, on_behalf_of=None) -> CallResult:
        """Pre-approve the EXACT request (requester, delegator, operation, args). The Engine approval gate still decides
        at commit: this records a single-use approval that the later propose consumes (see Core._commit)."""
        c, sub = self._c, self._c.subject(token)
        if sub is None or sub not in c.booted.principals:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token or unknown approver"})
        if not isinstance(operation, str) or operation not in c.ops:
            return CallResult("UNKNOWN", {"reason": "unknown operation"})
        clean = c.check_shape(operation, args, "approval")  # E-9: the request's own schema first; every later refusal of a valid one is governed
        if isinstance(clean, CallResult):
            return clean
        d = c.new_decision("approve", sub, on_behalf_of, operation, clean, None)
        if not isinstance(requester, str) or requester not in c.booted.principals:
            return c.finish(d, CallResult("DENIED", {"gate": "approval", "reason": "unknown requester"}))
        if not (c.ops[operation].get("approval") or {}).get("approver_operation"):
            return c.finish(d, CallResult("INVALID", {"gate": "approval", "reason": "operation takes no approval"}))
        who = c.principal(requester, on_behalf_of, operation)
        if isinstance(who, CallResult):
            return c.finish(d, who)
        with c.lock:
            if sub in c.excluded_approvers(requester, on_behalf_of):  # static chain + every edge issuer from the root to the requester
                return c.finish(d, CallResult("DENIED", {"gate": "approval", "reason": "approver is in the requester's delegation chain"}))
            if not c.holds_approval(sub, operation, clean):
                return c.finish(d, CallResult("DENIED", {"gate": "approval", "reason": "approver holds no approval capability for this request"}))
            res = c.finish(d, CallResult("OK", {"approval": "recorded"}))  # the approval is itself an anchored decision
            if res.status == "OK":
                c.ledger.add_approval(fingerprint(requester, on_behalf_of, operation, clean), sub, d["rid"])
            return res

    # ---- Gate 2: delegation, revocation, historical authority (PROT-H24) ---------------------------------------------
    def delegate(self, token: str, edge: dict, request_id: str) -> CallResult:
        return self._mutating(lambda: self._pub(self._authority_call("delegate", token, edge, request_id), request_id))

    def revoke(self, token: str, edge_id: str, request_id: str) -> CallResult:
        return self._mutating(lambda: self._pub(self._authority_call("revoke", token, {"edge_id": edge_id}, request_id), request_id))

    def _authority_call(self, kind: str, token: str, payload, rid) -> CallResult:
        c = self._c
        sub = c.subject(token)
        if sub is None or sub not in c.booted.principals:
            return CallResult("DENIED", {"gate": "identity", "reason": "token"})
        try:
            payload = json.loads(json.dumps(payload))
        except (TypeError, ValueError):
            return CallResult("INVALID", {"reason": "schema"})
        res = c.mutate_authority(kind, sub, payload, rid)
        self._auth_version = c.version()
        return res

    def authority_used(self, request_id: str) -> CallResult:
        if self._crashed:
            return self._DOWN
        with self._c.lock:
            led, used = self._c.ledger.get(request_id), self._c.ledger.get_meta(f"used:{request_id}")
        if led is None or led["state"] != "COMMITTED" or not used:
            return CallResult("INVALID", {"reason": "unknown_request"})
        return CallResult("OK", dict(used))

    # ---- Gate 3: constitutional authority (PROT-H25) ---------------------------------------------------------------
    def constitutional(self, token: str, action: dict, request_id: str) -> CallResult:
        return self._mutating(lambda: self._pub(self._constitutional(token, action, request_id), request_id))

    def _constitutional(self, token, action, request_id) -> CallResult:
        sub = self._c.subject(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "token"})
        return self._c.constitutional(sub, action, request_id)

    def set_governance(self, doc: dict) -> None:
        c = self._c
        if c is None:
            raise RuntimeError("deployment is crashed; restart() first")
        c.replace_governance(doc)

    def case_state(self, case_id: str):
        c = self._c
        return None if c is None else c.case_state(case_id)

    def authority_state(self) -> dict:
        return json.loads(canonical_bytes(self._c.auth))

    # ---- Gate 2: provenance (PROT-H27) ---------------------------------------------------------------------------------
    def replay(self, decision_id: str) -> ReplayResult:
        return _replay.replay(self, decision_id)

    def explain(self, decision_id: str) -> ReplayResult:
        return _replay.replay(self, decision_id)

    def current_artifact(self, kind: str, op) -> bytes:
        """The CURRENT spec's version of an artifact kind (used only by the fallback_to_current mutant)."""
        ops = self._args[3]
        c = self._c
        if kind == "authority":
            return canonical_bytes(c.auth if c is not None else self._args[4])
        return canonical_bytes(evid.policy_of(ops, op) if kind == "policy" else evid.contract_of(ops, op))


def _total(fn, fail):
    """E-3: no Deployment method raises; an internal error becomes a result (Crash is a BaseException and passes through)."""
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
    return wrapper


_CALL = lambda exc: CallResult("UNAVAILABLE", {"reason": f"internal_error: {type(exc).__name__}"})  # noqa: E731
_REPLAY = lambda exc: ReplayResult("UNRESOLVED", f"internal_error: {type(exc).__name__}")  # noqa: E731
for _n in ("call_tool", "direct", "read", "approve", "delegate", "revoke", "authority_used", "constitutional"):
    setattr(PaladinDeployment, _n, _total(getattr(PaladinDeployment, _n), _CALL))
for _n in ("replay", "explain"):
    setattr(PaladinDeployment, _n, _total(getattr(PaladinDeployment, _n), _REPLAY))
