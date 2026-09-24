"""F31 — "tool parameter injection -> MCP/action API -> normal gates
re-run server-side" — driven through the ACTUAL MCP tool call path (not
raw HTTP, unlike tests/integration/test_decision_service_injection.py,
whose payload set this file reuses verbatim). Proves the MCP thin-client
layer adds NO new injection surface: services/decision_service/schemas.py's
identifier-pattern validation runs exactly once, server-side, regardless of
which client called it.
"""

from __future__ import annotations

import httpx

from mcp.server.fastmcp import FastMCP
from tests.agent.helpers import call_tool

INJECTION_PAYLOADS = [
    'WH-A" } ; DROP ALL ; #',
    '" || true || "',
    "WH-A\nSELECT * WHERE",
    "warehouse:WH-A#agent_grant",
]


def test_tool_parameter_injection_rejected_with_zero_effects(
    mcp_server_granted: FastMCP, wms_client: httpx.Client, granted_warehouse: str
):
    before_lots = wms_client.get("/inventory_lots", params={"warehouse_id": "WH-A"}).json()

    for payload in INJECTION_PAYLOADS:
        result = call_tool(
            mcp_server_granted,
            "propose_transfer_inventory",
            {
                "source_warehouse": granted_warehouse,
                "destination_warehouse": payload,
                "part": "PX-0000",
                "quantity": 30,
            },
        )
        assert result.get("status_code") == 422, f"payload {payload!r} was not rejected via MCP: {result}"

    after_lots = wms_client.get("/inventory_lots", params={"warehouse_id": "WH-A"}).json()
    assert before_lots == after_lots, "tool-parameter injection via MCP must cause zero external WMS effects"


def test_tool_parameter_injection_in_get_object_rejected(mcp_server: FastMCP):
    for payload in INJECTION_PAYLOADS:
        result = call_tool(mcp_server, "get_object", {"kind": "work_order", "object_id": payload})
        assert "error" in result, f"payload {payload!r} was not rejected by get_object: {result}"


def test_tool_parameter_injection_in_work_order_id_rejected(mcp_server: FastMCP):
    for payload in INJECTION_PAYLOADS:
        result = call_tool(mcp_server, "query_work_order_risk", {"work_order_id": payload})
        assert "error" in result, f"payload {payload!r} was not rejected by query_work_order_risk: {result}"
