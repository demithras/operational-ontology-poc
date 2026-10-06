"""PaladinDeployment: the r3_shared Deployment protocol over the Paladin core (+ approve / set_authority extras)."""
from __future__ import annotations

import hashlib
import json

from paladin.core import AUDIENCE, Core, fingerprint, plain
from paladin.engine import CapabilityError, InvalidRequest, Principal
from paladin.surface import SurfaceFactory, UnknownTool, who_of
from paladin.worldbridge import state_from_world
from r3_shared.variant import CallResult, ToolDescriptor

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

    def __init__(self, domain, factory, verifier, ops_spec, auth_spec, clock, mutants=frozenset()):
        self._c = Core(domain, factory, verifier, ops_spec, auth_spec, clock, mutants)
        self._surfaces = SurfaceFactory(self._c.booted.ir)

    # ---- authority management ---------------------------------------------------------------
    def set_authority(self, auth_spec: dict) -> None:
        self._c.set_authority(auth_spec)
        self._surfaces = SurfaceFactory(self._c.booted.ir)

    def authority_version(self) -> str:
        """sha256 hex of the canonical JSON of the spec in force (r3_shared protocol)."""
        return hashlib.sha256(json.dumps(self._c.auth, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    # ---- surface (R3) -----------------------------------------------------------------------
    def _surface(self, sub: str, obo, propose):
        who = self._c.principal(sub, obo, None)
        if isinstance(who, CallResult):
            return who
        self._c.eng.store.current = state_from_world(self._c.eng.model, self._c._svc)
        types = sorted(self._c.eng.model.all("object_types"))
        return self._surfaces.surface(self._c.eng, who_of(who, None if who.delegated_by is None else who_of(who.delegated_by)),
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
        sub = self._c.subject(token)
        if sub is None or sub not in self._c.booted.principals:
            return []
        if "tool_overexposure" in self._c.mutants:  # MUTANT: every operation listed regardless of grants
            names = set(self._c.ops)
        else:
            names = set(self._exposed(sub, None))  # a delegate is always surfaced as its delegator's delegate
        return [ToolDescriptor(n, _schema(self._c.ops[n])) for n in sorted(names)]

    # ---- calls ------------------------------------------------------------------------------
    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None) -> CallResult:
        sub = self._c.subject(token, args)
        if sub is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token"})
        if not isinstance(name, str) or name not in self._c.ops:
            return CallResult("UNKNOWN", {"reason": "no such tool"})
        if not isinstance(args, dict):
            return CallResult("INVALID", {"gate": "inputs", "reason": "args must be an object"})
        who = self._c.principal(sub, on_behalf_of, name)
        if isinstance(who, CallResult):
            return who
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
            return CallResult("DENIED", {"gate": "surface", "reason": "operation not granted to this principal"})  # absent from its surface
        try:
            surf.call(tool, idempotency_key=request_id, **args)
        except UnknownTool:
            return CallResult("UNKNOWN", {"reason": "no such tool"})
        except TypeError as exc:
            return CallResult("INVALID", {"gate": "inputs", "reason": f"bad arguments: {exc}"})
        return box.get("r") or CallResult("INVALID", {"reason": "request was not issued"})

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None) -> CallResult:
        sub = self._c.subject(token, args)
        if sub is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token"})
        return self._c.run(sub, on_behalf_of, operation, args, request_id, "direct")

    def read(self, token, operation, args) -> CallResult:
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
        """Pre-approve the EXACT request (requester, delegator, operation, args). The Engine approval gate still decides
        at commit: this records a single-use approval that the later propose consumes (see Core._commit)."""
        c, sub = self._c, self._c.subject(token)
        if sub is None or sub not in c.booted.principals:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token or unknown approver"})
        if not isinstance(requester, str) or requester not in c.booted.principals:
            return CallResult("DENIED", {"gate": "approval", "reason": "unknown requester"})
        if not isinstance(operation, str) or operation not in c.ops:
            return CallResult("UNKNOWN", {"reason": "unknown operation"})
        if not (c.ops[operation].get("approval") or {}).get("approver_operation"):
            return CallResult("INVALID", {"gate": "approval", "reason": "operation takes no approval"})
        who = c.principal(requester, on_behalf_of, operation)
        if isinstance(who, CallResult):
            return who
        clean = c.check_shape(operation, args, "approval")
        if isinstance(clean, CallResult):
            return clean
        if sub in c.chain_pids(requester):
            return CallResult("DENIED", {"gate": "approval", "reason": "approver is in the requester's delegation chain"})
        if not c.holds_approval(sub, operation, clean):
            return CallResult("DENIED", {"gate": "approval", "reason": "approver holds no approval capability for this request"})
        c.approvals.setdefault(fingerprint(requester, c.delegator.get(requester), operation, clean), []).append(sub)
        return CallResult("OK", {"approval": "recorded"})

    def crash(self) -> None:
        raise NotImplementedError("crash/restart: not implemented yet - H29")

    def restart(self) -> None:
        raise NotImplementedError("crash/restart: not implemented yet - H29")
