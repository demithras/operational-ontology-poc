"""Environment configuration for the MCP agent surface (Phase 9, spec
06_decision_and_action_runtime.md "MCP layer (phase 2 only)").

Same split as services/decision_service/config.py's own docstring
describes: `from_container_env()` for the real docker-compose service
(SERVICE_DB_*-style env vars set in docker-compose.yml), `from_host_env()`
for host-run scripts/tests (tests/agent/, this repo's usual pytest
convention) — built from seed/db_env.py's helpers, the same pattern
services/decision_service/bootstrap_openfga.py already established.

`agent_id` is the ONE identity this server ever acts as. It is a startup
configuration value, never a request parameter — no MCP tool below ever
accepts an actor id, principal, or "act as" argument from the caller (F32:
"agent impersonates human ... impossible without explicit delegation").
Every mutating tool call is attributed to `agent_id` server-side; the real
human principal is resolved independently by decision_service itself from
OpenFGA's own `agent#principal` tuple (contracts/authorization/v1/model.fga),
never asserted by the MCP client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MCPConfig:
    decision_service_url: str
    ontology_hot_dsn: str
    openfga_api_url: str
    agent_id: str


def from_container_env() -> MCPConfig:
    return MCPConfig(
        decision_service_url=os.environ["DECISION_SERVICE_URL"],
        ontology_hot_dsn=os.environ["ONTOLOGY_HOT_DSN"],
        openfga_api_url=os.environ["OPENFGA_API_URL"],
        agent_id=os.environ.get("OO_MCP_AGENT_ID", "agent-1"),
    )


def from_host_env() -> MCPConfig:
    from seed import db_env

    db_env.load_dotenv()
    return MCPConfig(
        decision_service_url=db_env.decision_service_url(),
        ontology_hot_dsn=db_env.ontology_hot_dsn(),
        openfga_api_url=db_env.openfga_api_url(),
        agent_id=os.environ.get("OO_MCP_AGENT_ID", "agent-1"),
    )
