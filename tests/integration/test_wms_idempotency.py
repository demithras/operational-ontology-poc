"""WMS idempotency (docs/experiment/spec/06_decision_and_action_runtime.md
"Exactly-once language", F10/F11).

Uses a dedicated (part, warehouse) pair reset via the test-mode-only
`/_test/inventory/set` endpoint and a freshly-generated action_execution_id
per test, so these tests are hermetic and safe to re-run without a
`make reset` in between (unlike test_canonical_scenario.py, which
deliberately reuses fixed ids to exercise the real canonical incident).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

from tests.integration.conftest import get_lot

PART = "SKU-IDEMPOTENCY-TEST"
SOURCE = "WH-C"
DEST = "WH-D"


def _reset_stock(wms_client: httpx.Client, on_hand: int) -> None:
    wms_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": SOURCE, "on_hand": on_hand})
    wms_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": DEST, "on_hand": 0})


def test_same_key_same_body_sequential_replay_is_safe(wms_client: httpx.Client):
    _reset_stock(wms_client, 1000)
    action_id = f"ae-idem-{uuid.uuid4().hex}"
    body = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 30}

    r1 = wms_client.post("/transfers", json=body)
    assert r1.status_code == 200
    assert r1.json()["replayed"] is False

    r2 = wms_client.post("/transfers", json=body)
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True
    assert r2.json()["actual_quantity"] == r1.json()["actual_quantity"]

    lot = get_lot(wms_client, PART, SOURCE)
    # exactly one effect: 1000 - 30, not 1000 - 60
    assert lot["on_hand"] == 970


def test_same_key_different_body_is_409(wms_client: httpx.Client):
    _reset_stock(wms_client, 1000)
    action_id = f"ae-idem-conflict-{uuid.uuid4().hex}"
    first = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 30}
    second = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 31}

    r1 = wms_client.post("/transfers", json=first)
    assert r1.status_code == 200

    r2 = wms_client.post("/transfers", json=second)
    assert r2.status_code == 409
    assert "different request body" in r2.json()["error"]

    lot = get_lot(wms_client, PART, SOURCE)
    assert lot["on_hand"] == 970  # only the first (30-unit) request ever applied


def test_same_key_ten_concurrent_requests_exactly_one_effect(wms_client_factory):
    action_id = f"ae-idem-concurrent-{uuid.uuid4().hex}"
    body = {"action_execution_id": action_id, "source": SOURCE, "destination": DEST, "part": PART, "quantity": 25}

    setup_client = wms_client_factory()
    _reset_stock(setup_client, 1000)

    def fire(_: int) -> httpx.Response:
        with wms_client_factory() as client:
            return client.post("/transfers", json=body)

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(fire, range(10)))

    assert all(r.status_code == 200 for r in responses)
    committed_quantities = {r.json()["actual_quantity"] for r in responses}
    assert committed_quantities == {25}

    lot = get_lot(setup_client, PART, SOURCE)
    # exactly one 25-unit effect applied, no matter how many of the 10
    # requests raced to be "first"
    assert lot["on_hand"] == 975
