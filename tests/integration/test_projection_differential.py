"""Phase 4 item 2 (docs/experiment/briefs/phase4.md): drives the canonical
incident's ERP delay event through the REAL live stack (API -> CDC -> RDF
-> work_order_risk) and asserts the resulting hot-projection row matches
reference_model.derive()'s output for the SAME state — a genuine
differential test between two independent implementations (the RDF-sourced
services/projection_builder/compute.py and the pure-Python
reference_model/derive.py), not the same function invoked twice.

The oracle WorldState is built from LIVE reads of the real ERP/MES/WMS APIs
at test time, not from seed/fixtures/canonical_incident.yaml's static
numbers: other integration tests in this suite intentionally (and, in one
case, non-idempotently — tests/integration/test_cdc_ingestion.py's
`_test/inventory/set` bumps LOT-A-PX17's on_hand by +1 every run) mutate
WH-A/WH-B's PX-17 stock, and tests/integration/test_canonical_scenario.py
itself executes the canonical 60-unit transfer. Reading both sides (oracle
input and projection output) from the SAME live moment is what makes this a
correct "for the same state" comparison regardless of test run order or how
many times this suite has run against this stack before.
"""

from __future__ import annotations

from dataclasses import replace

import httpx

from reference_model.derive import derive
from reference_model.state import InventoryLot, PurchaseOrder, QUALITY_OK, WorkOrder, empty_state
from services.projection_builder.reader import (
    get_action_eligibility_summary,
    get_transfer_candidates,
    get_work_order_risk,
)
from tests.integration.conftest import wait_until
from tests.model.conftest import PART, PO_ID, WH_A, WH_B, WO_ID, build_actors, build_policy_config, build_warehouses

MES_PART_ID = "COMP-A17"
WMS_PART_ID = "SKU-88429"


def _live_oracle_shortage(erp_client: httpx.Client, mes_client: httpx.Client, wms_client: httpx.Client):
    """Builds a reference_model.state.WorldState from what the real source
    systems report RIGHT NOW and returns derive()'s WO-42 result — the
    independent oracle this test compares the live projection against."""
    wo = mes_client.get(f"/work_orders/{WO_ID}").json()
    requirement_qty = next(req["qty"] for req in wo["requirements"] if req["part_id"] == MES_PART_ID)

    po = erp_client.get(f"/purchase_orders/{PO_ID}").json()

    lot_a = next(
        row
        for row in wms_client.get("/inventory_lots", params={"part": WMS_PART_ID, "warehouse_id": WH_A}).json()
    )
    lot_b = next(
        row
        for row in wms_client.get("/inventory_lots", params={"part": WMS_PART_ID, "warehouse_id": WH_B}).json()
    )

    state = empty_state(build_warehouses(), build_actors(), build_policy_config())
    state = replace(
        state,
        work_orders={WO_ID: WorkOrder(WO_ID, wo["status"], wo["priority"], wo["planned_start"], WH_A, {PART: requirement_qty})},
        purchase_orders={PO_ID: PurchaseOrder(PO_ID, PART, po["lines"][0]["qty"], WH_A, expected_at=po["expected_at"], status=po["status"])},
        inventory={
            (PART, WH_A): InventoryLot("LOT-A-PX17", PART, WH_A, lot_a["on_hand"], lot_a["reserved"], QUALITY_OK, as_of=0),
            (PART, WH_B): InventoryLot("LOT-B-PX17", PART, WH_B, lot_b["on_hand"], lot_b["reserved"], QUALITY_OK, as_of=0),
        },
    )
    return derive(state)[WO_ID], lot_b["available"]


def test_work_order_risk_matches_reference_model_after_supplier_delay(
    erp_client: httpx.Client, mes_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn
):
    r = erp_client.post("/purchase_orders/PO-991/delay", json={"expected_at": 120, "reason": "transport_delay"})
    assert r.status_code == 200

    oracle, _lot_b_available = _live_oracle_shortage(erp_client, mes_client, wms_client)

    row = wait_until(
        lambda: (get_work_order_risk(ontology_hot_conn, WO_ID) or {}).get("shortage") == oracle.shortage
        and get_work_order_risk(ontology_hot_conn, WO_ID),
        timeout_s=30.0,
    )
    assert row, (
        f"work_order_risk row for WO-42 never converged to the live oracle's shortage={oracle.shortage} "
        "— check projection_builder health"
    )

    assert row["shortage"] == oracle.shortage
    assert row["at_risk"] == oracle.at_risk
    assert row["severity"] == ("CRITICAL" if oracle.at_risk else "MITIGATED")

    # docs/experiment/spec/03_domain_scenario.md's exact canonical numbers
    # hold whenever this is the FIRST time the delay has ever been applied
    # in this stack's lifetime (fresh `make reset && make seed`); on a
    # later re-run other tests may have already mitigated/moved stock, so
    # this assertion is deliberately conditional rather than absolute.
    if oracle.shortage == 60:
        assert oracle.at_risk is True

    # Traceability columns required by docs/experiment/briefs/phase4.md item 1.
    assert row["projection_definition_name"] == "work_order_risk"
    assert row["projection_definition_version"] == "1"
    assert len(row["projection_definition_sha256"]) == 64  # hex sha256
    assert row["ontology_contract_version"] == "v1"
    assert row["computed_at"] is not None
    assert row["as_of"] is not None
    assert row["source_positions"], "expected non-empty source event positions for a real, ingested work order"
    assert row["freshness_status"] in ("FRESH", "STALE")


def test_transfer_candidate_and_eligibility_summary_reflect_the_shortage(
    erp_client: httpx.Client, mes_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn
):
    erp_client.post("/purchase_orders/PO-991/delay", json={"expected_at": 120, "reason": "transport_delay"})
    oracle, lot_b_available = _live_oracle_shortage(erp_client, mes_client, wms_client)
    wait_until(
        lambda: (get_work_order_risk(ontology_hot_conn, WO_ID) or {}).get("shortage") == oracle.shortage,
        timeout_s=30.0,
    )

    if not oracle.at_risk:
        # Fully mitigated already (e.g. a prior test run's transfer covered
        # it) — no candidates are expected or required; nothing further to
        # assert about mitigation feasibility of a non-existent shortage.
        return

    candidates = wait_until(lambda: get_transfer_candidates(ontology_hot_conn, WO_ID) or None, timeout_s=30.0)
    assert candidates, "expected at least one transfer candidate (WH-B has surplus PX-17 stock)"
    wh_b_candidate = next(c for c in candidates if c["source_warehouse"] == "WH-B")
    assert wh_b_candidate["part"] == "PX-17"
    assert wh_b_candidate["destination_warehouse"] == "WH-A"
    assert wh_b_candidate["candidate_quantity"] == min(lot_b_available, oracle.shortage)

    summary = get_action_eligibility_summary(ontology_hot_conn, WO_ID)
    assert summary is not None
    assert summary["at_risk"] is True
    assert summary["shortage"] == oracle.shortage
    assert summary["transfer_candidate_count"] >= 1
