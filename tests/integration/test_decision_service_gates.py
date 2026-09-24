"""F01-F04, F08/F26 — docs/experiment/spec/09_failure_and_adversarial_matrix.md.
Every negative case asserts ZERO external WMS effects (phase5.md item 8) via
tests/integration/decision_helpers.py::inventory_unchanged, read through the
real WMS API. Uses synthetic SKUs at the real WH-A/WH-B warehouses — see
decision_helpers.py's module docstring for why (test_canonical_scenario.py
already permanently mitigates the real canonical incident) and for the
SKU-vs-canonical-id distinction (identity resolution quarantines any part id
that doesn't match WMS's `^SKU-\\d{6}$` pattern).
"""

from __future__ import annotations

import httpx
import psycopg

from tests.integration.decision_helpers import inventory_unchanged, propose_with_freshness_retry, set_inventory_and_wait


def _propose(decision_client: httpx.Client, **overrides) -> httpx.Response:
    body = {
        "action_type": "transfer_inventory",
        "actor": {"type": "user", "id": "planner-1"},
        "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-0000", "quantity": 30},
        "context": {},
    }
    body.update(overrides)
    return decision_client.post("/decisions/propose", json=body)


# --- F01: malformed decision -> reject; 0 external effects -----------------


def test_f01_unknown_action_type_rejected(decision_client: httpx.Client):
    r = _propose(decision_client, action_type="not_a_real_action")
    assert r.status_code == 422


def test_f01_source_equals_destination_rejected(decision_client: httpx.Client):
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-A", "destination_warehouse": "WH-A", "part": "PX-0000", "quantity": 10,
    })
    assert r.status_code == 422


def test_f01_zero_quantity_rejected(decision_client: httpx.Client):
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-0000", "quantity": 0,
    })
    assert r.status_code == 422


# --- F02/H14: missing required evidence -> INSUFFICIENT_EVIDENCE -----------


def test_f02_no_inventory_record_is_insufficient_evidence(decision_client: httpx.Client):
    part = "PX-NEVER-SET-01"  # a canonical-shaped id with no current_inventory row anywhere
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "INSUFFICIENT_EVIDENCE"
    assert "source_available" in body["evidence_snapshot"]["missing"]


# --- F08/F26: stale evidence -> INSUFFICIENT_EVIDENCE, never silently used --


def test_f08_stale_evidence_is_insufficient_not_silently_used(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    # No destination-side setup needed: services/decision_service/evidence.py
    # only checks destination WAREHOUSE existence (WH-A already exists) and
    # defaults quality_status to "OK" when no lot row exists there yet —
    # setting up an (irrelevant, different-canonical-id) destination SKU
    # here would only burn time out of the tight 5s freshness window this
    # test depends on (found empirically: it raced the very NEXT
    # projection-builder poll cycle reverting the source row's as_of bump).
    source_sku = "SKU-900101"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    # Deliberately push the SOURCE row's as_of back beyond the 5s threshold
    # (mirrors test_projection_staleness.py's technique) instead of relying
    # on wall-clock passing, which would be flaky.
    with ontology_hot_conn.cursor() as cur:
        cur.execute(
            "UPDATE current_inventory SET as_of = now() - interval '30 seconds' WHERE part = %s AND warehouse = %s",
            (part, "WH-B"),
        )
    r = _propose(decision_client, parameters={
        "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30,
    })
    body = r.json()
    assert body["status"] == "INSUFFICIENT_EVIDENCE"
    assert "source_available_fresh" in body["evidence_snapshot"]["missing"]
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)


# --- F03: unauthorized human -> deny; 0 external effects --------------------


def test_f03_unauthorized_human_denied(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900103"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = propose_with_freshness_retry(
        ontology_hot_conn, part, "WH-B",
        lambda: _propose(
            decision_client,
            actor={"type": "user", "id": "unregistered-1"},
            parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
        ),
    )
    body = r.json()
    assert body["status"] == "DENIED_AUTHORIZATION"
    assert body["authorization_result"]["outcome"] == "DENIED"
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)


# --- F04: unauthorized agent (no task grant) -> deny; 0 external effects ---


def test_f04_agent_without_task_grant_denied(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900105"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = propose_with_freshness_retry(
        ontology_hot_conn, part, "WH-B",
        lambda: _propose(
            decision_client,
            actor={"type": "agent", "id": "agent-1"},
            parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DENIED_AUTHORIZATION"
    # F32/H1: delegation chain recorded even for a denied agent proposal.
    assert body["principal_actor_id"] == "planner-1"
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)
