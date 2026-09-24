"""explain_decision — the one MCP tool that answers "why", built from
EXACTLY the same shape Phase 8's W5 workload proved sufficient at the
REST-API level (docs/experiment/implementation-notes.md Phase 8 item 2,
W5: "3 distinct calls ... all 7 forensic sub-questions answered
completely"): GET /decisions/{id}, then (if it was ever executed)
GET /executions/{action_execution_id} and GET /outcomes/{outcome_id}. No
direct RDF4J access from the MCP server at all — this keeps the whole MCP
layer a strict thin client of decision_service (spec 06), never a second
path into the semantic core that would need its own credentials/gates.
"""

from __future__ import annotations

from services.mcp.decision_client import DecisionServiceClient


def explain_decision(client: DecisionServiceClient, decision_id: str) -> dict:
    decision = client.get_decision(decision_id)

    explanation: dict = {
        "decision_id": decision_id,
        "status": decision.get("status"),
        "action_type": decision.get("action_type"),
        "parameters": decision.get("parameters"),
        "actor": {"id": decision.get("actor_id"), "type": decision.get("actor_type")},
        # F32/H1: the delegation chain, independently resolved server-side
        # at propose() time — never the same as `actor` unless this decision
        # was proposed directly by a human (see
        # tests/integration/test_decision_service_delegation.py).
        "principal_actor_id": decision.get("principal_actor_id"),
        "evidence_snapshot_id": decision.get("evidence_snapshot_id"),
        "authorization_result": decision.get("authorization_result"),
        "policy_result": decision.get("policy_result"),
        "conformance_result": decision.get("conformance_result"),
        "approved_by": decision.get("approved_by"),
        "approved_at": decision.get("approved_at"),
        "unavailable_gate": decision.get("unavailable_gate"),
        "execution": None,
        "outcome": None,
    }

    action_execution_id = f"AX-{decision_id}"
    execution = client.get_execution(action_execution_id)
    if execution is not None:
        explanation["execution"] = execution
        outcome_id = execution.get("outcomeId")
        if outcome_id:
            explanation["outcome"] = client.get_outcome(outcome_id)

    return explanation
