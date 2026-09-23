"""Shared fixture builders for tests/model/.

Builds the canonical incident described in
docs/experiment/spec/03_domain_scenario.md and mirrored in
seed/fixtures/canonical_incident.yaml.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from reference_model.state import (
    Actor,
    InventoryLot,
    PolicyConfig,
    PurchaseOrder,
    QUALITY_OK,
    ROLE_AGENT,
    ROLE_JUNIOR_PLANNER,
    ROLE_PLANNER,
    ROLE_SUPERVISOR,
    WO_PLANNED,
    Warehouse,
    WorkOrder,
    WorldState,
    empty_state,
)

PART = "PX-17"
WH_A = "WH-A"
WH_B = "WH-B"
WO_ID = "WO-42"
PO_ID = "PO-991"

TRANSFER_APPROVAL_THRESHOLD = 100
SAFETY_STOCK_WH_B = 50
MAX_EVIDENCE_FRESHNESS_S = 5


def build_actors() -> dict:
    return {
        "planner-1": Actor("planner-1", ROLE_PLANNER, frozenset({"region-1"})),
        "junior-1": Actor("junior-1", ROLE_JUNIOR_PLANNER, frozenset({"region-1"})),
        "supervisor-1": Actor("supervisor-1", ROLE_SUPERVISOR, frozenset({"region-1"})),
        "agent-1": Actor("agent-1", ROLE_AGENT, frozenset({"region-1"}), frozenset()),
        "agent-granted-1": Actor(
            "agent-granted-1", ROLE_AGENT, frozenset({"region-1"}), frozenset({"transfer_inventory"})
        ),
        "planner-outside-1": Actor("planner-outside-1", ROLE_PLANNER, frozenset({"region-2"})),
    }


def build_warehouses() -> dict:
    return {
        WH_A: Warehouse(WH_A, "region-1"),
        WH_B: Warehouse(WH_B, "region-1"),
    }


def build_policy_config(**overrides) -> PolicyConfig:
    defaults = dict(
        transfer_approval_threshold_units=TRANSFER_APPROVAL_THRESHOLD,
        safety_stock={(PART, WH_B): SAFETY_STOCK_WH_B},
        max_evidence_freshness_s=MAX_EVIDENCE_FRESHNESS_S,
    )
    defaults.update(overrides)
    return PolicyConfig(**defaults)


def pre_delay_state(clock: int = 0) -> WorldState:
    """WorldState exactly as of the start of
    docs/experiment/spec/03_domain_scenario.md, before the supplier-delay
    event: shortage should derive to 0 (PO-991 still counts as incoming
    before WO-42's planned_start)."""
    state = empty_state(build_warehouses(), build_actors(), build_policy_config(), clock=clock)
    state = replace(
        state,
        work_orders={WO_ID: WorkOrder(WO_ID, WO_PLANNED, "HIGH", 18, WH_A, {PART: 80})},
        purchase_orders={PO_ID: PurchaseOrder(PO_ID, PART, 100, WH_A, expected_at=8)},
        inventory={
            (PART, WH_A): InventoryLot("LOT-A-PX17", PART, WH_A, 20, 0, QUALITY_OK, as_of=clock),
            (PART, WH_B): InventoryLot("LOT-B-PX17", PART, WH_B, 140, 0, QUALITY_OK, as_of=clock),
        },
    )
    return state


def canonical_incident_state(clock: int = 0) -> WorldState:
    """WorldState after the supplier-delay event has been applied: shortage
    derives to 60, at_risk=True, matching
    docs/experiment/spec/03_domain_scenario.md exactly."""
    from reference_model.transitions import supplier_delay

    state = pre_delay_state(clock=clock)
    state, result = supplier_delay(state, PO_ID, new_expected_at=120, reason="transport_delay")
    assert result.ok
    return state


@pytest.fixture
def canonical_state() -> WorldState:
    return canonical_incident_state()
