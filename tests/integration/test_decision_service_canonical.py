"""H1 (decision-as-data completeness) + H10 (deterministic planner, no LLM) —
the canonical-shaped happy path: propose() reaches APPROVED end to end
through evidence -> authz -> policy -> SHACL-validated RDF4J write, with
every H1-required field present and resolvable via GET.

Uses a synthetic part at the real WH-A/WH-B warehouses with the SAME
transfer quantity as docs/experiment/spec/03_domain_scenario.md's canonical
incident (60 units) — see tests/integration/decision_helpers.py's module
docstring for why the literal canonical WO-42/PX-17 fixture cannot be reused
here (test_canonical_scenario.py already permanently mitigates it via a
direct WMS call).
"""

from __future__ import annotations

import httpx
import psycopg

from services.decision_service import planner
from tests.integration.decision_helpers import propose_with_freshness_retry, set_inventory_and_wait

H1_REQUIRED_FIELDS = [
    "decision_id", "decision_type", "actor_id", "action_type", "action_version",
    "parameters", "status", "ontology_version", "shape_set_version",
    "authorization_model_version", "policy_bundle_version", "created_at",
]


def test_canonical_shaped_transfer_reaches_approved_with_complete_decision_record(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900501"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=200)

    r = propose_with_freshness_retry(
        ontology_hot_conn, part, "WH-B",
        lambda: decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 60},
            },
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED", body

    # H1: every required field/link is present and resolvable — fetched
    # fresh via GET (not just the propose response), matching H1's
    # "completeness ratio across all successfully governed decisions".
    fetched = decision_client.get(f"/decisions/{body['decision_id']}").json()
    for field in H1_REQUIRED_FIELDS:
        assert fetched.get(field) not in (None, ""), f"H1: required field {field!r} missing/empty"
    assert fetched["evidence_snapshot"]["missing"] == []
    assert fetched["authorization_result"]["outcome"] == "ALLOWED"
    assert fetched["policy_result"]["outcome"] == "allow"
    assert fetched["conformance_result"]["outcome"] == "CONFORMS"
    assert fetched["decision_content_hash"] is not None


def test_h10_deterministic_planner_recommends_without_any_llm(ontology_hot_conn: psycopg.Connection):
    """H10: 'the canonical incident and all core acceptance tests pass with
    a deterministic rule-based planner ... no LLM'. This only asserts the
    planner's OWN pure-rule recommendation shape against whatever real
    at-risk work orders exist in the seeded dataset — it does not submit the
    recommendation (a real at-risk generated-dataset candidate may carry
    other real-world complications, e.g. a quarantined destination, which is
    itself a legitimate F05 case exercised in
    tests/integration/test_decision_service_policy.py, not a planner bug)."""
    with ontology_hot_conn.cursor() as cur:
        cur.execute("SELECT work_order_id FROM work_order_risk WHERE at_risk = true ORDER BY work_order_id LIMIT 1")
        row = cur.fetchone()
    if row is None:
        import pytest

        pytest.skip("no at-risk work order in the current seeded dataset to exercise the planner against")
    work_order_id = row[0]
    recommendation = planner.recommend_transfer_for_work_order(ontology_hot_conn, work_order_id)
    assert recommendation is not None
    assert recommendation["action_type"] == "transfer_inventory"
    params = recommendation["parameters"]
    assert params["quantity"] > 0
    assert params["source_warehouse"] != "" and params["destination_warehouse"] != ""
