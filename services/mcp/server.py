"""The MCP server itself — spec 06_decision_and_action_runtime.md "MCP
layer (phase 2 only)": exposes ONLY get_object, query_work_order_risk,
list_transfer_candidates, propose_transfer_inventory, get_decision,
execute_approved_decision, explain_decision. There is no `run_sql`,
`write_triple`, unrestricted HTTP, or source-system-credential tool
anywhere in this module (or this whole package) — F04/F30's "undisclosed/
unauthorized tool" adversarial scenario is closed structurally: such a
tool does not exist to be discovered, not merely hidden.

Every mutating tool (`propose_transfer_inventory`, `execute_approved_decision`)
acts as `config.agent_id` ONLY — no tool signature below accepts an actor,
principal, or "on behalf of" argument, so there is no parameter for a
compromised planner to inject (F31/F32). All governance (authorization,
policy, SHACL, approval-hash, immutable-tuple verification) happens
exactly once, server-side, inside decision_service
(services/mcp/decision_client.py) — this module never evaluates a gate
itself and could not fabricate an ALLOW/APPROVED result even if a caller's
prompt told it to (F30: "the expected safety property is architectural").
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.mcp.authz_filter import agent_has_any_transfer_grant
from services.mcp.config import MCPConfig
from services.mcp.decision_client import DecisionServiceClient, DecisionServiceError
from services.mcp.explain import explain_decision as _explain_decision
from services.mcp.projections import InvalidObjectRequest
from services.mcp.projections import get_object as _get_object
from services.mcp.projections import list_transfer_candidates as _list_transfer_candidates
from services.mcp.projections import query_work_order_risk as _query_work_order_risk

ALLOWED_TOOL_NAMES = frozenset(
    {
        "get_object",
        "query_work_order_risk",
        "list_transfer_candidates",
        "propose_transfer_inventory",
        "get_decision",
        "execute_approved_decision",
        "explain_decision",
    }
)


def _gate_error(exc: DecisionServiceError) -> dict:
    return {"error": str(exc), "status_code": exc.status_code, "detail": exc.detail}


def build_server(config: MCPConfig, *, host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    mcp = FastMCP(
        "oo-poc-agent-surface",
        instructions=(
            "Operational-ontology agent surface (Phase 9). Every mutating tool acts as "
            f"agent:{config.agent_id}; the human principal is resolved server-side from "
            "OpenFGA, never asserted by the caller. Authorization, policy, and structural "
            "conformance gates are re-run in full inside decision_service on every call — "
            "this server cannot approve/allow/execute anything on its own."
        ),
        host=host,
        port=port,
    )
    client = DecisionServiceClient(config.decision_service_url)
    mcp._oo_decision_client = client  # for close_server() below

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:  # pragma: no cover - trivial
        return JSONResponse({"status": "ok", "service": "mcp", "agent_id": config.agent_id})

    @mcp.tool()
    def get_object(kind: str, object_id: str, warehouse: str | None = None) -> dict:
        """Inspect one allowed ontology/hot-view object. `kind` is
        'work_order' or 'inventory_lot' ('inventory_lot' also needs
        `warehouse`). Read-only; never mutates anything."""
        try:
            row = _get_object(config.ontology_hot_dsn, kind, object_id, warehouse)
        except InvalidObjectRequest as exc:
            return {"error": str(exc)}
        return row or {"error": "not found"}

    @mcp.tool()
    def query_work_order_risk(work_order_id: str) -> dict:
        """Read the current shortage/at-risk/priority state of one work
        order from the hot projection. Read-only."""
        try:
            row = _query_work_order_risk(config.ontology_hot_dsn, work_order_id)
        except InvalidObjectRequest as exc:
            return {"error": str(exc)}
        return row or {"error": "not found"}

    @mcp.tool()
    def list_transfer_candidates(work_order_id: str) -> list[dict]:
        """List candidate source warehouses that could mitigate one
        at-risk work order. Descriptive only — no authorization/policy
        evaluation happens here (that only happens on propose)."""
        try:
            return _list_transfer_candidates(config.ontology_hot_dsn, work_order_id)
        except InvalidObjectRequest as exc:
            return [{"error": str(exc)}]

    @mcp.tool()
    def propose_transfer_inventory(
        source_warehouse: str,
        destination_warehouse: str,
        part: str,
        quantity: int,
        work_order: str | None = None,
    ) -> dict:
        """Propose a transfer_inventory decision. Every gate is evaluated
        server-side inside decision_service; this tool never itself
        decides anything and always acts as this server's own configured
        agent identity, never a caller-supplied one."""
        try:
            return client.propose_transfer_inventory(
                config.agent_id, source_warehouse, destination_warehouse, part, quantity, work_order
            )
        except DecisionServiceError as exc:
            return _gate_error(exc)

    @mcp.tool()
    def get_decision(decision_id: str) -> dict:
        """Fetch a Decision's current governed record by id."""
        try:
            return client.get_decision(decision_id)
        except DecisionServiceError as exc:
            return _gate_error(exc)

    @mcp.tool()
    def execute_approved_decision(decision_id: str) -> dict:
        """Execute a decision that has already reached APPROVED.
        decision_service re-verifies the immutable content hash and
        current status server-side before starting the durable workflow —
        this tool cannot execute anything not already approved, and a
        stale/mutated decision is rejected there, not here."""
        try:
            return client.execute_approved_decision(decision_id)
        except DecisionServiceError as exc:
            return _gate_error(exc)

    @mcp.tool()
    def explain_decision(decision_id: str) -> dict:
        """Explain why a decision reached its status: evidence, policy,
        authorization, approval, execution, and observed outcome."""
        try:
            return _explain_decision(client, decision_id)
        except DecisionServiceError as exc:
            return _gate_error(exc)

    # spec 06: "Tool discovery itself should be authorization-filtered
    # where feasible" — see services/mcp/authz_filter.py's own docstring
    # for exactly what this does and does not guarantee.
    if not agent_has_any_transfer_grant(config.openfga_api_url, config.agent_id):
        mcp.remove_tool("propose_transfer_inventory")
        mcp.remove_tool("execute_approved_decision")

    return mcp


def close_server(mcp: FastMCP) -> None:
    client = getattr(mcp, "_oo_decision_client", None)
    if client is not None:
        client.close()
