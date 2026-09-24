"""F05-F07 — OPA policy denial, approval-required, SHACL conformance.
Every negative case asserts ZERO external WMS effects (phase5.md item 8).
See tests/integration/decision_helpers.py for the SKU-vs-canonical-id
convention this suite relies on, and its module docstring for why no
post-setup "freshness touch" is needed (Phase 5 fix: watermark-based
evidence freshness).
"""

from __future__ import annotations

import httpx
import psycopg

from tests.integration.decision_helpers import inventory_unchanged, set_inventory_and_wait


def _propose(decision_client: httpx.Client, **overrides) -> httpx.Response:
    body = {
        "action_type": "transfer_inventory",
        "actor": {"type": "user", "id": "planner-1"},
        "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-0000", "quantity": 30},
        "context": {},
    }
    body.update(overrides)
    return decision_client.post("/decisions/propose", json=body)


# --- F05: policy deny (quarantine) -> deny; explanation recorded; 0 effects


def test_f05_quarantined_source_denied_by_policy(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900201"
    part = set_inventory_and_wait(
        wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100, quality_status="QUARANTINE"
    )
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30,
    })
    body = r.json()
    assert body["status"] == "DENIED_POLICY"
    assert body["authorization_result"]["outcome"] == "ALLOWED"  # policy is the boundary that denies here, not authz
    assert "source_quarantined" in body["policy_result"]["reasons"]
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)


def test_f05_safety_stock_breach_denied_by_policy(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    # No part-specific override in contracts/policies/v1/data.json ->
    # default_safety_stock=10. available=15, quantity=10 -> remaining=5 < 10.
    source_sku = "SKU-900202"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=15)
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 10,
    })
    body = r.json()
    assert body["status"] == "DENIED_POLICY"
    assert "safety_stock_breach" in body["policy_result"]["reasons"]
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 15)


# --- F06: approval required -> no execution before valid approval ----------


def test_f06_above_threshold_requires_approval_and_cannot_execute(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900203"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=1000)
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 150,
    })
    body = r.json()
    assert body["status"] == "REQUIRES_APPROVAL"
    assert body["decision_content_hash"] is not None
    assert body["policy_result"]["obligations"] == [{"type": "approval", "relation": "can_approve_large_transfer"}]

    execute_resp = decision_client.post(f"/decisions/{body['decision_id']}/execute")
    assert execute_resp.status_code == 409, "must not be executable before approval"
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 1000)


# --- F07: invalid RDF transition -> transaction rejected --------------------


def test_f07_forced_conformance_violation_recorded_as_invalid_conformance(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900204"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = _propose(
        decision_client,
        parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
        context={"force_invalid_conformance": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "INVALID_CONFORMANCE"
    assert body["conformance_result"]["outcome"] == "VIOLATED"
    assert len(body["conformance_result"]["violations"]) > 0
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)
    # H1 completeness: even a forced-invalid decision still resolves via GET
    # with all required fields present (never silently dropped, F07).
    fetched = decision_client.get(f"/decisions/{body['decision_id']}").json()
    assert fetched["status"] == "INVALID_CONFORMANCE"
    assert fetched["ontology_version"]
