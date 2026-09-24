"""F31 live proof — docs/experiment/spec/09_failure_and_adversarial_matrix.md
"tool parameter injection -> MCP/action API -> normal gates re-run
server-side". Added after a security review flagged SPARQL-injection risk in
services/decision_service/evidence.py's warehouse-existence ASK query
(f-string interpolation of a caller-supplied warehouse id).

The pure-validation proof (services/decision_service/schemas.py's
`ProposeRequest` rejects the payload before it can reach anything) is
tests/contracts/test_decision_service_input_validation.py — Level 1, no
network. THIS test is the live end-to-end proof: a real HTTP POST with a
hostile warehouse id must be rejected with zero external WMS effects and
zero RDF mutation (no new decision graph committed to RDF4J at all).
"""

from __future__ import annotations

import httpx

INJECTION_PAYLOADS = [
    'WH-A" } ; DROP ALL ; #',
    '" || true || "',
    "WH-A\nSELECT * WHERE",
    "warehouse:WH-A#agent_grant",
]


def test_sparql_injection_attempt_rejected_with_zero_effects(decision_client: httpx.Client, wms_client: httpx.Client):
    before_lots = wms_client.get("/inventory_lots", params={"warehouse_id": "WH-A"}).json()

    for payload in INJECTION_PAYLOADS:
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {
                    "source_warehouse": "WH-B",
                    "destination_warehouse": payload,
                    "part": "PX-0000",
                    "quantity": 30,
                },
            },
        )
        # Rejected at the input boundary (F01/F31) — never becomes a
        # Decision, never reaches evidence gathering's SPARQL query at all.
        assert r.status_code == 422, f"payload {payload!r} was not rejected: {r.status_code} {r.text}"

    after_lots = wms_client.get("/inventory_lots", params={"warehouse_id": "WH-A"}).json()
    assert before_lots == after_lots, "injection attempt must cause zero external WMS effects"


def test_sparql_injection_in_actor_id_rejected(decision_client: httpx.Client):
    for payload in INJECTION_PAYLOADS:
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": payload},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-0000", "quantity": 30},
            },
        )
        assert r.status_code == 422, f"actor.id={payload!r} was not rejected: {r.status_code} {r.text}"


def test_sparql_injection_in_approve_hash_rejected(decision_client: httpx.Client):
    r = decision_client.post(
        "/decisions/D-does-not-exist/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": 'sha\\" } DROP GRAPH <x> #'},
    )
    assert r.status_code == 422
