"""Best-effort authorization-filtered tool discovery (spec 06: "Tool
discovery itself should be authorization-filtered where feasible").

This is UX/discovery only, NEVER the security boundary — every mutating
tool's real enforcement is the server-side OpenFGA + OPA + SHACL gate chain
inside decision_service, re-run in full on every call regardless of
whether this filter ran or what it decided (F04/F30/F31: "even a fully
compromised planner cannot bypass hard enforcement" — a planner that
somehow saw a tool it wasn't entitled to would still be denied when it
tried to use it; see tests/agent/). This module answers one question:
"does this server's configured agent identity currently hold ANY
`agent_grant` tuple on any warehouse" — if not, `propose_transfer_inventory`
and `execute_approved_decision` are not worth advertising (an agent with
zero task-bound grants can propose but will always be DENIED_AUTHORIZATION,
and can never reach an APPROVED decision to execute).

Best-effort: on ANY failure to reach OpenFGA, defaults to NOT filtering
(shows every tool) — a discovery-layer false negative here would look like
a capability the agent doesn't actually have; a discovery-layer false
POSITIVE (showing a tool it turns out to be denied for) costs nothing
beyond a normal DENIED_AUTHORIZATION response, which is exactly what would
happen anyway on an OpenFGA outage. Never fabricates certainty either way.
"""

from __future__ import annotations

from services.decision_service import authz


def agent_has_any_transfer_grant(openfga_api_url: str, agent_id: str) -> bool:
    store_id = authz.resolve_store_id(openfga_api_url)
    if store_id is None:
        return True  # can't determine -> don't hide capability (see module docstring)
    tuples = authz._read_all_tuples(openfga_api_url, store_id)
    if tuples is None:
        return True
    fga_user = f"agent:{agent_id}"
    return any(t.get("relation") == "agent_grant" and t.get("user") == fga_user for t in tuples)
