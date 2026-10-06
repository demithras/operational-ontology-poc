"""Agent tool surface: an MCP-style tool list generated from the operation catalog and filtered by the policy engine.
A convenience layer ABOVE the service API: hiding a tool is never the only defense (the service re-authorizes)."""
from __future__ import annotations

from r3_shared.variant import CallResult, ToolDescriptor

from .models_gen import OPERATION_MODELS
from .service import Service

_JSON_TYPE = {"integer": {"type": "integer"}, "resource": {"type": "string", "minLength": 1}, "string": {"type": "string"},
              "json": {}}


def input_schema(op: str) -> dict:
    sch = OPERATION_MODELS[op].SCHEMA
    return {"type": "object", "additionalProperties": False,
            "properties": {n: dict(_JSON_TYPE[k]) for n, k, _ in sch},
            "required": [n for n, _, r in sch if r]}


class ToolSurface:
    def __init__(self, service: Service):
        self._svc = service

    def visible(self, token: str) -> list[str]:
        sub = self._svc.authenticate(token)
        if sub is None or self._svc.crashed:
            return []
        if self._svc.mutant("tool_overexposure"):  # BUG: lists everything regardless of grants (service still enforces)
            return self._svc.operations
        return self._svc.policy.exposed_operations(sub, self._svc.operations)

    def tools(self, token: str) -> list[ToolDescriptor]:
        return [ToolDescriptor(op, input_schema(op)) for op in self.visible(token)]

    def call_tool(self, token: str, name: str, args: dict, on_behalf_of: str | None = None,
                  request_id: str | None = None) -> CallResult:
        if self._svc.crashed:
            return CallResult("UNAVAILABLE", {"reason": "crashed"})
        if self._svc.authenticate(token) is None:
            return CallResult("DENIED", {"reason": "invalid_token"})
        if name not in self.visible(token):
            return CallResult("DENIED", {"reason": "tool_not_available"})
        return self._svc.execute(token, name, args, on_behalf_of, request_id)
