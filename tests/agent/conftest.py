"""Shared fixtures for tests/agent/ (Phase 9 — H9 "agent capability is
bounded by the same hard controls as human/API callers", spec 09's F04/
F30-F34 adversarial scenarios). Reuses tests/integration/conftest.py's own
stack-reachability fixtures directly (pytest fixtures are plain importable
functions), same pattern tests/replay/conftest.py already established.

The "compromised planner" fixture (`mcp_server`) is built EXACTLY the way
the real container would be (services/mcp/server.py::build_server) — no
test-only backdoor, no relaxed gate. Every adversarial scenario in this
package drives the MCP tool surface (or, for a handful of scenarios spec 09
frames as "the agent tries X" where X has no MCP tool at all — e.g.
approving its own proposal — decision_service's raw HTTP API directly,
since a compromised agent is not assumed to be MCP-obedient) and asserts
against REAL WMS ground truth (tests.integration.decision_helpers.
inventory_unchanged), never against the decision record's own self-report.
"""

from __future__ import annotations

import httpx
import pytest

from seed import db_env
from services.decision_service import authz
from services.mcp.config import MCPConfig, from_host_env
from services.mcp.server import build_server, close_server
from tests.integration.conftest import (  # noqa: F401
    decision_client,
    decision_service_reachable,
    ingestion_client,
    ontology_hot_conn,
    rdf4j_client,
    rdf4j_reachable,
    stack_up,
    wms_client,
)

AGENT_ID = "agent-1"  # contracts/authorization/v1/tuples.yaml: principal planner-1


@pytest.fixture()
def mcp_config(decision_service_reachable: bool) -> MCPConfig:
    if not decision_service_reachable:
        pytest.skip("decision_service not reachable — run 'make up' first")
    return from_host_env()


@pytest.fixture()
def openfga_store_id(decision_service_reachable: bool) -> str:
    db_env.load_dotenv()
    store_id = authz.resolve_store_id(db_env.openfga_api_url())
    if store_id is None:
        pytest.skip("OpenFGA 'oo-poc' store not bootstrapped — run 'make up' first")
    return store_id


@pytest.fixture()
def mcp_server(mcp_config: MCPConfig):
    """The real server object (services/mcp/server.py::build_server) — same
    code a container running `python3 -m services.mcp` executes, just
    driven in-process for deterministic testing (no transport/session
    overhead, matching this repo's own tests/contracts's in-process pyshacl
    convention for the same reason)."""
    mcp = build_server(mcp_config)
    yield mcp
    close_server(mcp)


def write_agent_grant(store_id: str, warehouse: str, agent_id: str = AGENT_ID) -> None:
    r = httpx.post(
        f"{db_env.openfga_api_url()}/stores/{store_id}/write",
        json={"writes": {"tuple_keys": [{"user": f"agent:{agent_id}", "relation": "agent_grant", "object": f"warehouse:{warehouse}"}]}},
        timeout=5.0,
    )
    assert r.status_code in (200, 400), r.text  # 400 tolerated: "already exists"


def delete_agent_grant(store_id: str, warehouse: str, agent_id: str = AGENT_ID) -> None:
    r = httpx.post(
        f"{db_env.openfga_api_url()}/stores/{store_id}/write",
        json={"deletes": {"tuple_keys": [{"user": f"agent:{agent_id}", "relation": "agent_grant", "object": f"warehouse:{warehouse}"}]}},
        timeout=5.0,
    )
    assert r.status_code in (200, 400), r.text


@pytest.fixture()
def granted_warehouse(openfga_store_id: str):
    """Grants agent-1 `agent_grant` on WH-B for the duration of one test,
    then revokes it — the minimum real task-bound grant most adversarial
    scenarios need to even REACH a policy/evidence gate (an ungranted agent
    is denied before any of those run, which is a real but less interesting
    proof for scenarios that are specifically about what happens AFTER
    authorization passes)."""
    write_agent_grant(openfga_store_id, "WH-B")
    try:
        yield "WH-B"
    finally:
        delete_agent_grant(openfga_store_id, "WH-B")


@pytest.fixture()
def mcp_server_granted(granted_warehouse: str, mcp_config: MCPConfig):
    """A server built AFTER `granted_warehouse`'s tuple write lands — real
    fixture-dependency ordering (not parameter-list position, which pytest
    does NOT guarantee build order for), because services/mcp/authz_filter.py's
    tool-discovery filter runs ONCE at `build_server()` time. Building the
    plain `mcp_server` fixture first and granting afterward is exactly the
    F04 test this repo's own delegation test already proves is meaningful
    (Phase 5: "revoked-grant-denies-immediately" needs a real HTTP re-Check,
    never a cached earlier answer) — this fixture is for the OTHER
    scenarios, which need `propose_transfer_inventory`/
    `execute_approved_decision` actually present to test what happens
    AFTER the gate, not tool-discovery filtering itself."""
    mcp = build_server(mcp_config)
    yield mcp
    close_server(mcp)
