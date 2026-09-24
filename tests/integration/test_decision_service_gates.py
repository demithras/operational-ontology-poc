"""F01-F04 — docs/experiment/spec/09_failure_and_adversarial_matrix.md.
Every negative case asserts ZERO external WMS effects (phase5.md item 8) via
tests/integration/decision_helpers.py::inventory_unchanged, read through the
real WMS API. Uses synthetic SKUs at the real WH-A/WH-B warehouses — see
decision_helpers.py's module docstring for why (test_canonical_scenario.py
already permanently mitigates the real canonical incident) and for the
SKU-vs-canonical-id distinction (identity resolution quarantines any part id
that doesn't match WMS's `^SKU-\\d{6}$` pattern).

F08/F26 (stale evidence) moved to
tests/integration/test_decision_service_dependency_outage.py — Phase 5 fix
(watermark-based evidence freshness): staleness is now a PIPELINE property
(a stalled connector/builder), not a per-row property, so it is simulated
the same way as the other real-infrastructure outages in that file, not by
editing a row's `as_of` via SQL. Freshness no longer depends on how recently
a specific row's data changed (see decision_helpers.py's module docstring),
so `set_inventory_and_wait` here needs no post-setup "touch" of any kind —
propose() is called directly, any time after setup.
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


# --- F03: unauthorized human -> deny; 0 external effects --------------------


def test_f03_unauthorized_human_denied(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    source_sku = "SKU-900103"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = _propose(
        decision_client,
        actor={"type": "user", "id": "unregistered-1"},
        parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
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
    r = _propose(
        decision_client,
        actor={"type": "agent", "id": "agent-1"},
        parameters={"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DENIED_AUTHORIZATION"
    # F32/H1: delegation chain recorded even for a denied agent proposal.
    assert body["principal_actor_id"] == "planner-1"
    assert inventory_unchanged(wms_client, source_sku, "WH-B", 100)
