"""Pure-Python unit tests for services/projection_builder/compute.py — no
RDF4J/Postgres required (docs/experiment/spec/08_test_strategy.md Level 1).

Regression test for a bug found empirically during Phase 4 implementation
against the real SEED=42 dataset: MES's bom_requirements table has no
UNIQUE(work_order_id, part_id) constraint, so a work order can carry MORE
THAN ONE requirement row for the same part. Before the fix,
compute_work_order_risk evaluated each duplicate row independently against
the SAME available/incoming supply (double-counting it) and produced
duplicate (work_order, part, source_warehouse) transfer_candidates rows,
which crashed `make rebuild-projections` with a Postgres UniqueViolation on
transfer_candidates_pkey the first time a real work order (WO-0146,
part PX-0251) happened to have both a duplicate requirement row AND an
actual shortage.
"""

from __future__ import annotations

from services.projection_builder.compute import (
    compute_transfer_candidates,
    compute_work_order_risk,
)

WO = "https://example.local/factory/instance/WorkOrder/WO-X"
PART = "https://example.local/factory/instance/Part/PX-1"
WH_A = "https://example.local/factory/instance/Warehouse/WH-A"
WH_B = "https://example.local/factory/instance/Warehouse/WH-B"


def _work_order(status="PLANNED", planned_start="18", warehouse=WH_A):
    return {"wo": WO, "status": status, "plannedStart": planned_start, "whUri": warehouse}


def test_duplicate_requirement_rows_for_same_part_are_summed_not_double_counted():
    work_orders = [_work_order()]
    requirements = [
        {"wo": WO, "req": WO + "/req/1", "partUri": PART, "qty": "50"},
        {"wo": WO, "req": WO + "/req/2", "partUri": PART, "qty": "30"},
    ]
    inventory_available = [{"lot": "lot1", "partUri": PART, "whUri": WH_A, "available": "20"}]
    incoming_lines = []

    risk = compute_work_order_risk(work_orders, requirements, inventory_available, incoming_lines)

    # Combined requirement is 50 + 30 = 80, evaluated ONCE against the 20
    # available (not 50-20=30 plus 30-20=10=40, which would double-count the
    # single pool of 20 available units against each duplicate row).
    assert risk["WO-X"].shortage == 60
    assert risk["WO-X"].at_risk is True
    assert risk["WO-X"].part_shortfalls == (("PX-1", 60),)


def test_transfer_candidates_never_duplicates_a_candidate_id_across_duplicate_requirement_rows():
    work_orders = [_work_order()]
    requirements = [
        {"wo": WO, "req": WO + "/req/1", "partUri": PART, "qty": "50"},
        {"wo": WO, "req": WO + "/req/2", "partUri": PART, "qty": "30"},
    ]
    inventory_available = [
        {"lot": "lot-a", "partUri": PART, "whUri": WH_A, "available": "20"},
        {"lot": "lot-b", "partUri": PART, "whUri": WH_B, "available": "500"},
    ]
    risk = compute_work_order_risk(work_orders, requirements, inventory_available, [])
    candidates = compute_transfer_candidates(risk, inventory_available)

    candidate_ids = [c.candidate_id for c in candidates]
    assert len(candidate_ids) == len(set(candidate_ids)), f"duplicate candidate_id(s) in {candidate_ids}"
    assert candidate_ids == ["WO-X|PX-1|WH-B"]
    assert candidates[0].candidate_quantity == 60  # min(available=500, shortage=60)


def test_terminal_work_orders_are_excluded():
    work_orders = [_work_order(status="DONE"), _work_order(status="CANCELLED")]
    risk = compute_work_order_risk(work_orders, [], [], [])
    assert risk == {}
