"""Every WMS fault mode from docs/experiment/spec/06_decision_and_action_runtime.md
"WMS fake API requirements" / 09_failure_and_adversarial_matrix.md, verified
observable afterwards via GET — never trusting the initial HTTP response
alone (docs/experiment/briefs/phase2.md item 5).
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from tests.integration.conftest import get_lot

PART = "SKU-FAULT-TEST"
SOURCE = "WH-C"
DEST = "WH-D"


def _reset_stock(wms_client: httpx.Client, on_hand: int = 1000) -> None:
    wms_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": SOURCE, "on_hand": on_hand})
    wms_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": DEST, "on_hand": 0})


def _arm(wms_client: httpx.Client, mode: str, action_id: str, params: dict | None = None) -> None:
    r = wms_client.post(
        "/_test/faults/arm",
        json={"mode": mode, "scope": "action_execution_id", "action_execution_id": action_id, "params": params or {}},
    )
    assert r.status_code == 200


def test_return_500_before_commit_leaves_no_row_no_effect(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-500-{uuid.uuid4().hex}"
    _arm(wms_client, "return_500_before_commit", action_id)

    r = wms_client.post(
        "/transfers",
        json={"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 10},
    )
    assert r.status_code == 500

    assert wms_client.get(f"/transfers/{action_id}").status_code == 404
    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 1000


def test_return_200_without_commit_leaves_no_row_no_effect(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-200nc-{uuid.uuid4().hex}"
    _arm(wms_client, "return_200_without_commit", action_id)

    r = wms_client.post(
        "/transfers",
        json={"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 10},
    )
    # the fault fabricates a 200 body, but never observed_success at the
    # WMS layer: GET afterwards proves nothing happened.
    assert r.status_code == 200

    assert wms_client.get(f"/transfers/{action_id}").status_code == 404
    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 1000


def test_partial_commit_moves_exactly_the_partial_quantity(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-partial-{uuid.uuid4().hex}"
    _arm(wms_client, "partial_commit", action_id, params={"actual_quantity": 50})

    r = wms_client.post(
        "/transfers",
        json={"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 60},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PARTIAL"
    assert r.json()["actual_quantity"] == 50

    row = wms_client.get(f"/transfers/{action_id}").json()
    assert row["requested_quantity"] == 60
    assert row["actual_quantity"] == 50
    assert row["status"] == "PARTIAL"

    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 950  # 1000 - 50, not - 60


def test_delay_commit_eventually_commits(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-delay-{uuid.uuid4().hex}"
    _arm(wms_client, "delay_commit", action_id, params={"delay_s": 1.0})

    started = time.monotonic()
    r = wms_client.post(
        "/transfers",
        json={"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 10},
    )
    elapsed = time.monotonic() - started

    assert r.status_code == 200
    assert r.json()["status"] == "COMMITTED"
    assert elapsed >= 0.9  # the delay actually happened, not a no-op flag

    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 990


def test_commit_then_timeout_recovers_via_idempotent_replay(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-timeout-{uuid.uuid4().hex}"
    _arm(wms_client, "commit_then_timeout", action_id, params={"timeout_s": 2.0})

    body = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 10}

    with pytest.raises(httpx.TimeoutException):
        wms_client.post("/transfers", json=body, timeout=httpx.Timeout(0.3))

    # F14: the commit already happened server-side even though the caller
    # never saw the confirmation. A retry with the SAME key/body resolves
    # via idempotent replay to the one real effect, not a second one.
    r_retry = wms_client.post("/transfers", json=body)
    assert r_retry.status_code == 200
    assert r_retry.json()["replayed"] is True
    assert r_retry.json()["actual_quantity"] == 10

    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 990  # exactly one 10-unit effect, not two


def test_duplicate_response_still_dedupes_on_replay(wms_client: httpx.Client, wms_faults_reset):
    _reset_stock(wms_client)
    action_id = f"ae-fault-dup-{uuid.uuid4().hex}"
    _arm(wms_client, "duplicate_response", action_id)

    body = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 10}
    r1 = wms_client.post("/transfers", json=body)
    assert r1.status_code == 200
    assert r1.json()["status"] == "COMMITTED"

    # Simulates the caller (or a network layer) re-delivering the same
    # request (F10/F19) — must dedupe to the same single effect.
    r2 = wms_client.post("/transfers", json=body)
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True

    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 990
