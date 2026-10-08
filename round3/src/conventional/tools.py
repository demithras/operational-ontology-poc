"""Agent tool surface: an MCP-style tool list generated from the operation catalog and filtered by the policy engine.
A convenience layer ABOVE the service API: hiding a tool is never the only defense (the service re-authorizes)."""
from __future__ import annotations

from r3_shared.variant import CallResult, ToolDescriptor

from r3_shared.disclosure import tool_schema

from .service import Service


class ToolSurface:
    def __init__(self, service: Service):
        self._svc = service

    def visible(self, token: str) -> list[str]:
        sub = self._svc.authenticate(token)
        if sub is None or self._svc.crashed:
            return []
        if self._svc.mutant("tool_overexposure") or self._svc.mutant("hidden_tool_schema"):
            return self._svc.operations  # BUG: lists everything regardless of grants/the subject (service still enforces)
        ops = set(self._svc.policy.exposed_operations(sub, self._svc.operations)) | self._svc.emergency_ops(sub)
        return [o for o in self._svc.operations if o in ops]

    def tools(self, token: str) -> list[ToolDescriptor]:
        defs = self._svc.op_defs
        return [ToolDescriptor(op, tool_schema(defs[op])) for op in self.visible(token)]  # P1e-5: frozen derivation, verbatim

    def call_tool(self, token: str, name: str, args: dict, on_behalf_of: str | None = None,
                  request_id: str | None = None) -> CallResult:
        if self._svc.crashed:
            return CallResult("UNAVAILABLE", {"reason": "crashed"})
        if self._svc.authenticate(token) is None:
            return CallResult("DENIED", {"reason": "invalid_token"})
        hidden = name not in self.visible(token)  # a hidden tool is still a governed refusal: the service decides (E-8)
        return self._svc.execute(token, name, args, on_behalf_of, request_id, _kind="call_tool", _hidden=hidden)
