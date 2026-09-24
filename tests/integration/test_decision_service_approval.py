"""Approval flow — docs/experiment/spec/06_decision_and_action_runtime.md
"Human approval" + F33 ("approval replay on changed decision -> rejected due
decision hash mismatch"). Full REQUIRES_APPROVAL -> APPROVED happy path, a
junior_planner correctly denied approval authority (08_test_strategy.md
"junior denied protected approval"), and the F33 hash-mismatch rejection.
"""

from __future__ import annotations

import httpx
import psycopg

from tests.integration.decision_helpers import set_inventory_and_wait


def _propose_requiring_approval(decision_client: httpx.Client, wms_client: httpx.Client, conn: psycopg.Connection, sku: str) -> dict:
    part = set_inventory_and_wait(wms_client, conn, sku, "WH-B", on_hand=1000)
    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 150},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "REQUIRES_APPROVAL"
    return body


def test_supervisor_can_approve_and_decision_becomes_approved(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    decision = _propose_requiring_approval(decision_client, wms_client, ontology_hot_conn, "SKU-900301")
    r = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": decision["decision_content_hash"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by"] == "supervisor-1"
    assert body["approval_decision_hash"] == decision["decision_content_hash"]

    fetched = decision_client.get(f"/decisions/{decision['decision_id']}").json()
    assert fetched["status"] == "APPROVED"
    assert fetched["approved_by"] == "supervisor-1"


def test_junior_planner_denied_protected_approval(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    decision = _propose_requiring_approval(decision_client, wms_client, ontology_hot_conn, "SKU-900302")
    r = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "junior-1", "decision_content_hash": decision["decision_content_hash"]},
    )
    assert r.status_code == 403
    fetched = decision_client.get(f"/decisions/{decision['decision_id']}").json()
    assert fetched["status"] == "REQUIRES_APPROVAL", "a denied approval attempt must not change decision state"


def test_f33_approval_rejected_on_hash_mismatch(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    decision = _propose_requiring_approval(decision_client, wms_client, ontology_hot_conn, "SKU-900303")
    wrong_hash = "0" * 64
    r = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": wrong_hash},
    )
    assert r.status_code == 409
    fetched = decision_client.get(f"/decisions/{decision['decision_id']}").json()
    assert fetched["status"] == "REQUIRES_APPROVAL"
    assert fetched["approved_by"] is None


def test_approval_on_already_approved_decision_rejected(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    decision = _propose_requiring_approval(decision_client, wms_client, ontology_hot_conn, "SKU-900304")
    ok = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": decision["decision_content_hash"]},
    )
    assert ok.status_code == 200
    replay = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": decision["decision_content_hash"]},
    )
    assert replay.status_code == 409, "cannot approve a decision that is already APPROVED (not REQUIRES_APPROVAL)"
