"""The concurrency race from docs/experiment/spec/09_failure_and_adversarial_matrix.md
"Concurrency tests": stock=100, two DIFFERENT decisions each want 80 —
exactly one may succeed, the other must be rejected (never negative stock).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

from tests.integration.conftest import get_lot

PART = "SKU-RACE-TEST"
SOURCE = "WH-C"
DEST = "WH-D"


def test_two_concurrent_80_unit_requests_against_100_stock(wms_client_factory):
    setup_client = wms_client_factory()
    setup_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": SOURCE, "on_hand": 100})
    setup_client.post("/_test/inventory/set", json={"part": PART, "warehouse_id": DEST, "on_hand": 0})

    action_a = f"ae-race-a-{uuid.uuid4().hex}"
    action_b = f"ae-race-b-{uuid.uuid4().hex}"

    def fire(action_id: str) -> httpx.Response:
        with wms_client_factory() as client:
            return client.post(
                "/transfers",
                json={
                    "action_execution_id": action_id,
                    "source": SOURCE,
                    "destination": DEST,
                    "part": PART,
                    "quantity": 80,
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        r_a, r_b = list(pool.map(fire, [action_a, action_b]))

    statuses = sorted([r_a.status_code, r_b.status_code])
    # Allowed: exactly one 200 (COMMITTED) and one 409 (insufficient stock).
    # Forbidden: both 200 (would drive stock negative).
    assert statuses == [200, 409], (r_a.status_code, r_a.text, r_b.status_code, r_b.text)

    winner, loser = (r_a, r_b) if r_a.status_code == 200 else (r_b, r_a)
    assert winner.json()["actual_quantity"] == 80
    assert "insufficient available stock" in loser.json()["error"]

    source_lot = get_lot(setup_client, PART, SOURCE)
    dest_lot = get_lot(setup_client, PART, DEST)
    assert source_lot["on_hand"] == 20  # 100 - 80, never negative
    assert source_lot["reserved"] == 0
    assert dest_lot["on_hand"] == 80

    # the loser's transfer row is recorded as FAILED with zero effect, not
    # silently dropped (docs/experiment/spec/06 outcome predicate honesty)
    loser_id = action_b if loser is r_b else action_a
    loser_row = setup_client.get(f"/transfers/{loser_id}").json()
    assert loser_row["status"] == "FAILED"
    assert loser_row["actual_quantity"] == 0
