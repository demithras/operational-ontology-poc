"""PaladinDeployment: the r3_shared Deployment protocol over the Paladin core (+ approve / set_authority extras)."""
from __future__ import annotations

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
    def set_authority(self, auth_spec: dict) -> int:
        v = self._c.set_authority(auth_spec)
        self._surfaces = SurfaceFactory(self._c.booted.ir)
        return v

    def authority_version(self) -> int:
        return self._c.authority_version

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
        if obo is not None:  # a delegated surface only offers what the delegation lists
            ops &= set(self._c.delegations.get((sub, obo), ()))
        return ops

    def tools(self, token: str) -> list[ToolDescriptor]:
        sub = self._c.subject(token)
        if sub is None or sub not in self._c.booted.principals:
            return []
        if "tool_overexposure" in self._c.mutants:  # MUTANT: every operation listed regardless of grants
            names = set(self._c.ops)
        else:
            names = set(self._exposed(sub, None))
            for (agent, obo) in self._c.delegations:
                if agent == sub and obo in self._c.booted.principals:
                    names |= self._exposed(sub, obo)
        return [ToolDescriptor(n, _schema(self._c.ops[n])) for n in sorted(names)]

    # ---- calls ------------------------------------------------------------------------------
    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None) -> CallResult:
        sub = self._c.subject(token, args)
        if sub is None:
            return CallResult("DENIED", {"gate": "identity", "reason": "invalid token"})
        if not isinstance(name, str) or name not in self._c.ops:
            return CallResult("UNKNOWN", {"reason": "no such tool"})
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
            return CallResult("UNKNOWN", {"reason": "no such tool"})  # absent from this principal's surface
        try:
            surf.call(tool, idempotency_key=request_id, **(args if isinstance(args, dict) else {}))
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

    def approve(self, token, request_id, approve: bool = True) -> CallResult:
        """Second-principal approval of a PENDING_APPROVAL request (not part of the Variant protocol)."""
        c, sub = self._c, self._c.subject(token)
        p = c.pending.get(request_id)
        if sub is None or sub not in c.booted.principals or p is None:
            return CallResult("DENIED", {"gate": "approval", "reason": "no such pending request or bad identity"})
        approver = c.booted.principals[sub]
        proposer_chain = {p["sub"], *([p["obo"]] if p["obo"] else [])}
        if sub in proposer_chain:
            return CallResult("DENIED", {"gate": "approval", "reason": "approver is in the requester's delegation chain"})
        if not approve:
            return CallResult("DENIED", {"gate": "approval", "reason": "rejected"})
        res = c._commit(approver, p["op"], {}, request_id, approve=(p["execution"], approver))
        if res.status == "OK":
            c.ledger[request_id] = {"fp": p["fp"], "status": "OK", "body": plain(res.body), "sub": p["sub"], "obo": p["obo"], "op": p["op"]}
            c.pending.pop(request_id, None)
        return res

    def crash(self) -> None:
        raise NotImplementedError("crash/restart: not implemented yet - H29")

    def restart(self) -> None:
        raise NotImplementedError("crash/restart: not implemented yet - H29")
