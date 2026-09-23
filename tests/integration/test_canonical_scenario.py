"""Executes the canonical incident (docs/experiment/spec/03_domain_scenario.md)
manually through the three fake source-system APIs, per
docs/experiment/briefs/phase2.md item 5 ("canonical scenario executable
manually via the APIs").

Every mutating call uses a FIXED, hardcoded action_execution_id /
idempotency-equivalent request, so this test is safe to re-run against an
already-seeded stack without a `make reset` in between: the second run's
PO-991 delay call just re-asserts the same DELAYED state, and the second
run's transfer call hits WMS's idempotent-replay path (docs/experiment/spec/06)
instead of moving stock a second time. Assertions check absolute end state,
never a before/after delta.
"""

from __future__ import annotations

import httpx

CANONICAL_TRANSFER_ID = "ae-canonical-transfer-60"

ERP_PART_ID = "PART-00192"
MES_PART_ID = "COMP-A17"
WMS_PART_ID = "SKU-88429"


def test_step1_erp_initial_po_is_open(erp_client: httpx.Client):
    r = erp_client.get("/purchase_orders/PO-991")
    assert r.status_code == 200
    po = r.json()
    assert po["supplier_id"] == "S-7"
    assert any(line["part_id"] == ERP_PART_ID and line["qty"] == 100 for line in po["lines"])


def test_step2_supplier_delay_event(erp_client: httpx.Client):
    r = erp_client.post("/purchase_orders/PO-991/delay", json={"expected_at": 120, "reason": "transport_delay"})
    assert r.status_code == 200
    po = r.json()
    assert po["status"] == "DELAYED"
    assert po["expected_at"] == 120
    assert po["delay_reason"] == "transport_delay"

    # persisted, not just echoed back
    r2 = erp_client.get("/purchase_orders/PO-991")
    assert r2.json()["status"] == "DELAYED"
    assert r2.json()["expected_at"] == 120


def test_step3_mes_work_order_requires_shortage_quantity(mes_client: httpx.Client):
    r = mes_client.get("/work_orders/WO-42")
    assert r.status_code == 200
    wo = r.json()
    assert wo["status"] == "PLANNED"
    assert wo["priority"] == "HIGH"
    assert wo["planned_start"] == 18
    assert wo["warehouse"] == "WH-A"
    assert any(req["part_id"] == MES_PART_ID and req["qty"] == 80 for req in wo["requirements"])


def test_step4_transfer_60_units_wh_b_to_wh_a(wms_client: httpx.Client):
    before_a = wms_client.get("/inventory_lots/LOT-A-PX17").json()
    before_b = wms_client.get("/inventory_lots/LOT-B-PX17").json()

    r = wms_client.post(
        "/transfers",
        json={
            "action_execution_id": CANONICAL_TRANSFER_ID,
            "source": "WH-B",
            "destination": "WH-A",
            "part": WMS_PART_ID,
            "quantity": 60,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["actual_quantity"] == 60
    assert body["status"] == "COMMITTED"

    # Absolute end state: the canonical incident's starting stock (20 @ WH-A,
    # 140 @ WH-B) after exactly one 60-unit transfer, regardless of whether
    # this is the first run since `make reset` or a re-run hitting the
    # idempotent-replay path.
    after_a = wms_client.get("/inventory_lots/LOT-A-PX17").json()
    after_b = wms_client.get("/inventory_lots/LOT-B-PX17").json()
    assert after_a["on_hand"] == 80
    assert after_a["available"] == 80
    assert after_b["on_hand"] == 80
    assert after_b["available"] == 80

    # sanity: the two lots moved by the same 60 units, opposite direction
    assert after_a["on_hand"] - before_a["on_hand"] == before_b["on_hand"] - after_b["on_hand"]


def test_step5_transfer_record_retrievable(wms_client: httpx.Client):
    r = wms_client.get(f"/transfers/{CANONICAL_TRANSFER_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["source_warehouse"] == "WH-B"
    assert body["destination_warehouse"] == "WH-A"
    assert body["part"] == WMS_PART_ID
    assert body["requested_quantity"] == 60
    assert body["actual_quantity"] == 60
    assert body["status"] == "COMMITTED"
