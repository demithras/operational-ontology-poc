"""F31 (docs/experiment/spec/09_failure_and_adversarial_matrix.md: "tool
parameter injection -> MCP/action API -> normal gates re-run server-side")
regression test, added after a security review flagged SPARQL-injection risk
in services/decision_service/evidence.py's warehouse-existence ASK query
(f-string interpolation of a caller-supplied warehouse id).

Level 1 (pure pydantic validation, no docker/network) — proves the
INPUT-BOUNDARY defense: services/decision_service/schemas.py's
`ProposeRequest` rejects any identifier-shaped field containing SPARQL/Rego
metacharacters BEFORE the request body can reach evidence gathering,
authorization, or policy evaluation. A live end-to-end proof that this
actually stops a real proposal with zero external effects and zero RDF
mutation lives in tests/integration/test_decision_service_gates.py's
`test_sparql_injection_attempt_rejected_with_zero_effects`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.common.sparql_escape import escape_sparql_literal
from services.decision_service.schemas import ApproveRequest, ProposeRequest

INJECTION_PAYLOADS = [
    'WH-A" } ; DROP ALL ; #',
    '" || true || "',
    "WH-A\" }} }} #",
    "WH-A\nSELECT * WHERE",
    "WH-A' OR '1'='1",
    "warehouse:WH-A#agent_grant",  # attempted OpenFGA object-string smuggling
    "",  # empty string
    "a" * 65,  # over length
]


@pytest.mark.parametrize("bad_value", INJECTION_PAYLOADS)
def test_propose_request_rejects_malicious_warehouse_id(bad_value: str):
    with pytest.raises(ValidationError):
        ProposeRequest(
            action_type="transfer_inventory",
            actor={"type": "user", "id": "planner-1"},
            parameters={
                "source_warehouse": bad_value,
                "destination_warehouse": "WH-A",
                "part": "PX-17",
                "quantity": 60,
            },
        )


@pytest.mark.parametrize("bad_value", INJECTION_PAYLOADS)
def test_propose_request_rejects_malicious_actor_id(bad_value: str):
    with pytest.raises(ValidationError):
        ProposeRequest(
            action_type="transfer_inventory",
            actor={"type": "user", "id": bad_value},
            parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 60},
        )


@pytest.mark.parametrize("bad_value", INJECTION_PAYLOADS)
def test_propose_request_rejects_malicious_context_value(bad_value: str):
    with pytest.raises(ValidationError):
        ProposeRequest(
            action_type="transfer_inventory",
            actor={"type": "user", "id": "planner-1"},
            parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 60},
            context={"work_order_id": bad_value},
        )


def test_propose_request_accepts_well_formed_ids():
    req = ProposeRequest(
        action_type="transfer_inventory",
        actor={"type": "user", "id": "planner-1"},
        parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 60},
        context={"work_order_id": "WO-42"},
    )
    assert req.parameters["source_warehouse"] == "WH-B"


@pytest.mark.parametrize("bad_value", ['not-64-hex', "g" * 64, ""])
def test_approve_request_rejects_malformed_hash(bad_value: str):
    with pytest.raises(ValidationError):
        ApproveRequest(approver_id="supervisor-1", decision_content_hash=bad_value)


def test_escape_sparql_literal_neutralizes_quote_and_brace_breakout():
    hostile = 'WH-A" } ; SELECT * WHERE { ?s ?p ?o'
    escaped = escape_sparql_literal(hostile)
    # The escaped form, re-embedded in a double-quoted literal, must contain
    # no UNESCAPED double-quote — i.e. every `"` in the input is preceded by
    # a backslash in the output.
    assert '\\"' in escaped
    rebuilt = f'"{escaped}"'
    # Count of raw (non-escaped) quote characters must be exactly the two
    # wrapping ones.
    unescaped_quotes = rebuilt.replace('\\"', "").count('"')
    assert unescaped_quotes == 2


def test_escape_sparql_literal_neutralizes_newline_injection():
    hostile = 'WH-A"\nDROP GRAPH <http://example/all>'
    escaped = escape_sparql_literal(hostile)
    assert "\n" not in escaped
