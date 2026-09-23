"""Concurrency race test — docs/experiment/spec/09_failure_and_adversarial_matrix.md
"Concurrency tests" / docs/experiment/spec/01_hypotheses.md H5.

    initial stock = 100
    Decision A wants 80
    Decision B wants 80

Allowed: one success + one rejection/re-evaluation.
Forbidden: stock = -60.

Both decisions are proposed from the same (initially valid) evidence; the
race is resolved at execute_transfer time via the execution-time re-check.
"""

from __future__ import annotations

from dataclasses import replace

from reference_model.invariants import check_invariants
from reference_model.state import (
    ALL_BUGS,
    BUG_SKIP_EXECUTION_RECHECK,
    DECISION_APPROVED,
    DECISION_OBSERVED_SUCCESS,
    Actor,
    InventoryLot,
    PolicyConfig,
    QUALITY_OK,
    ROLE_PLANNER,
    Warehouse,
    empty_state,
)
from reference_model.transitions import execute_transfer, propose_transfer

PART = "PX-99"
WH_SRC = "WH-SRC"
WH_DST = "WH-DST"


def _race_state():
    warehouses = {WH_SRC: Warehouse(WH_SRC, "region-1"), WH_DST: Warehouse(WH_DST, "region-1")}
    actors = {"planner-1": Actor("planner-1", ROLE_PLANNER, frozenset({"region-1"}))}
    policy = PolicyConfig(
        transfer_approval_threshold_units=100,
        safety_stock={(PART, WH_SRC): 0},
        max_evidence_freshness_s=5,
    )
    state = empty_state(warehouses, actors, policy, clock=0)
    state = replace(
        state,
        inventory={(PART, WH_SRC): InventoryLot("LOT-SRC", PART, WH_SRC, 100, 0, QUALITY_OK, as_of=0)},
    )
    return state


def test_concurrent_80_80_against_100_resolves_one_success_one_rejection():
    state = _race_state()

    state, decision_a = propose_transfer(state, "planner-1", WH_SRC, WH_DST, PART, 80)
    state, decision_b = propose_transfer(state, "planner-1", WH_SRC, WH_DST, PART, 80)
    assert decision_a.status == DECISION_APPROVED
    assert decision_b.status == DECISION_APPROVED

    state, result_a = execute_transfer(state, decision_a.decision_id, f"idem-{decision_a.decision_id}")
    state, result_b = execute_transfer(state, decision_b.decision_id, f"idem-{decision_b.decision_id}")

    outcomes = {result_a.status, result_b.status}
    assert result_a.ok != result_b.ok or DECISION_OBSERVED_SUCCESS in outcomes
    # exactly one of the two produced an OBSERVED_SUCCESS effect
    successes = [r for r in (result_a, result_b) if r.status == DECISION_OBSERVED_SUCCESS]
    rejections = [r for r in (result_a, result_b) if r.status != DECISION_OBSERVED_SUCCESS]
    assert len(successes) == 1
    assert len(rejections) == 1
    assert rejections[0].status == "EXECUTION_FAILED"

    # never negative
    final_lot = state.inventory[(PART, WH_SRC)]
    assert final_lot.on_hand == 20
    assert final_lot.available >= 0
    assert not check_invariants(state)
    assert len(state.transfer_effects) == 1


def test_bug_skip_execution_recheck_allows_negative_inventory():
    """Same race, but with BUG_SKIP_EXECUTION_RECHECK active: both decisions
    execute, driving on_hand negative. This proves the invariant/bug-catch
    machinery actually detects the defect it claims to (see also
    tests/model/test_bug_detection.py)."""
    state = _race_state()
    bugs = frozenset({BUG_SKIP_EXECUTION_RECHECK})

    state, decision_a = propose_transfer(state, "planner-1", WH_SRC, WH_DST, PART, 80, bugs=bugs)
    state, decision_b = propose_transfer(state, "planner-1", WH_SRC, WH_DST, PART, 80, bugs=bugs)

    state, result_a = execute_transfer(
        state, decision_a.decision_id, f"idem-{decision_a.decision_id}", bugs=bugs
    )
    state, result_b = execute_transfer(
        state, decision_b.decision_id, f"idem-{decision_b.decision_id}", bugs=bugs
    )

    assert result_a.status == DECISION_OBSERVED_SUCCESS
    assert result_b.status == DECISION_OBSERVED_SUCCESS

    violations = check_invariants(state)
    assert violations, "expected the skipped-recheck bug to produce an invariant violation"
    assert any("available" in v for v in violations)
