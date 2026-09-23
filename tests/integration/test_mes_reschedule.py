"""docs/experiment/spec/03_domain_scenario.md state-machine invariant:
"DONE/CANCELLED -> reschedule forbidden". Uses generated (not canonical
fixture) work orders so it never touches WO-42, which
test_canonical_scenario.py asserts an exact planned_start for.
"""

from __future__ import annotations

import httpx
import pytest


def _first_non_canonical(work_orders: list[dict]) -> dict | None:
    return next((wo for wo in work_orders if wo["work_order_id"] != "WO-42"), None)


def test_reschedule_planned_work_order_succeeds(mes_client: httpx.Client):
    candidates = mes_client.get("/work_orders", params={"status": "PLANNED"}).json()
    wo = _first_non_canonical(candidates)
    if wo is None:
        pytest.skip("no non-canonical PLANNED work order in this seed")

    r = mes_client.post(f"/work_orders/{wo['work_order_id']}/reschedule", json={"new_planned_start": 999})
    assert r.status_code == 200
    assert r.json()["planned_start"] == 999

    r2 = mes_client.get(f"/work_orders/{wo['work_order_id']}")
    assert r2.json()["planned_start"] == 999


@pytest.mark.parametrize("status", ["DONE", "CANCELLED"])
def test_reschedule_terminal_work_order_is_409(mes_client: httpx.Client, status: str):
    candidates = mes_client.get("/work_orders", params={"status": status}).json()
    wo = _first_non_canonical(candidates)
    if wo is None:
        pytest.skip(f"no non-canonical {status} work order in this seed")

    before = mes_client.get(f"/work_orders/{wo['work_order_id']}").json()

    r = mes_client.post(f"/work_orders/{wo['work_order_id']}/reschedule", json={"new_planned_start": 1})
    assert r.status_code == 409
    assert r.json()["status"] == status

    after = mes_client.get(f"/work_orders/{wo['work_order_id']}").json()
    assert after["planned_start"] == before["planned_start"]  # unchanged
