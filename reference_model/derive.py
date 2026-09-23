"""Derived operational facts — docs/experiment/spec/03_domain_scenario.md
"Derived operational fact" / docs/experiment/spec/12_implementation_plan.md
Phase 4's `work_order_risk` projection, computed here in pure form as the
oracle those projections must agree with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

from reference_model.state import WO_DONE, WO_CANCELLED, WorldState


@dataclass(frozen=True)
class WorkOrderRisk:
    work_order_id: str
    shortage: int
    at_risk: bool


def _available_at(state: WorldState, part: str, warehouse: str) -> int:
    lot = state.inventory.get((part, warehouse))
    return lot.available if lot is not None else 0


def _incoming_before(state: WorldState, part: str, warehouse: str, deadline: int) -> int:
    """Sum of purchase-order quantity for `part` into `warehouse` that is
    still pending (not yet received/cancelled) and expected to arrive at or
    before `deadline`."""
    total = 0
    for po in state.purchase_orders.values():
        if po.part != part or po.destination_warehouse != warehouse:
            continue
        if po.status in ("RECEIVED", "CANCELLED"):
            continue
        if po.expected_at <= deadline:
            total += po.qty
    return total


def derive(state: WorldState) -> Dict[str, WorkOrderRisk]:
    """Per work-order shortage/at_risk, for every open (non-terminal) work
    order.

    shortage = max(0, sum(required - available_at_wo_warehouse - incoming_before_planned_start))
    at_risk = shortage > 0

    Verified against the canonical incident
    (seed/fixtures/canonical_incident.yaml): WO-42 requires 80 PX-17 at
    WH-A (available 20). Before the supplier delay, PO-991 (100 units,
    expected T+8h) arrives before planned_start (T+18h), so shortage =
    max(0, 80 - 20 - 100) = 0. After the delay (expected_at -> T+5d = 120,
    which is after planned_start = 18), the PO no longer counts as incoming,
    so shortage = max(0, 80 - 20 - 0) = 60, at_risk = True — matching
    docs/experiment/spec/03_domain_scenario.md exactly.
    """
    result: Dict[str, WorkOrderRisk] = {}
    for wo in state.work_orders.values():
        if wo.status in (WO_DONE, WO_CANCELLED):
            continue
        shortage = 0
        for part, required_qty in wo.requirements.items():
            available = _available_at(state, part, wo.warehouse)
            incoming = _incoming_before(state, part, wo.warehouse, wo.planned_start)
            shortage += max(0, required_qty - available - incoming)
        result[wo.work_order_id] = WorkOrderRisk(
            work_order_id=wo.work_order_id,
            shortage=shortage,
            at_risk=shortage > 0,
        )
    return result


def work_order_risk(state: WorldState, work_order_id: str) -> WorkOrderRisk:
    derived = derive(state)
    if work_order_id not in derived:
        # Work order is terminal (DONE/CANCELLED) or unknown: treat as
        # zero-shortage, not-at-risk rather than raising — callers that
        # need existence-checking should consult state.work_orders directly.
        return WorkOrderRisk(work_order_id=work_order_id, shortage=0, at_risk=False)
    return derived[work_order_id]


def total_on_hand_by_part(state: WorldState) -> Mapping[str, int]:
    """Sum of on_hand across all warehouses, per part. Used by tests to
    check conservation of units across transfer-only sequences
    (docs/experiment/spec/01_hypotheses.md H5)."""
    totals: Dict[str, int] = {}
    for (part, _warehouse), lot in state.inventory.items():
        totals[part] = totals.get(part, 0) + lot.on_hand
    return totals
