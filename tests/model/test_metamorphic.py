"""Metamorphic tests — docs/experiment/spec/08_test_strategy.md
"Metamorphic tests":

- replaying a processed command with the same idempotency key must not
  create a second effect;
- adding irrelevant facts should not change an action decision;
- renaming a source-local identifier while preserving identity mapping
  should not change the canonical result.
"""

from __future__ import annotations

from dataclasses import replace

from reference_model.state import (
    DECISION_APPROVED,
    DECISION_OBSERVED_SUCCESS,
    InventoryLot,
    QUALITY_OK,
)
from reference_model.transitions import execute_transfer, propose_transfer, resolve_id, add_id_mapping

from .conftest import PART, WH_A, WH_B, WO_ID


def test_duplicate_execution_same_key_no_second_effect(canonical_state):
    state = canonical_state
    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)
    assert decision.status == DECISION_APPROVED

    key = f"idem-{decision.decision_id}"
    state, result1 = execute_transfer(state, decision.decision_id, key)
    assert result1.status == DECISION_OBSERVED_SUCCESS

    state_after_first = state
    state, result2 = execute_transfer(state, decision.decision_id, key)

    assert result2.status == "DEDUPED_REPLAY"
    assert result2.execution_id == result1.execution_id
    assert state.transfer_effects == state_after_first.transfer_effects
    assert state.inventory == state_after_first.inventory
    assert len(state.transfer_effects) == 1


def test_irrelevant_lot_does_not_change_decision(canonical_state):
    state = canonical_state

    # propose against the unmodified state
    state1, decision1 = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    # add an entirely unrelated lot for a different part/warehouse, then propose again
    unrelated = InventoryLot("LOT-IRRELEVANT", "PX-IRRELEVANT", "WH-A", 999, 0, QUALITY_OK, as_of=state.clock)
    inv = dict(state.inventory)
    inv[("PX-IRRELEVANT", "WH-A")] = unrelated
    state2 = replace(state, inventory=inv)
    state2, decision2 = propose_transfer(state2, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    assert decision1.status == decision2.status == DECISION_APPROVED
    assert decision1.evidence_gate == decision2.evidence_gate
    assert decision1.authz_gate == decision2.authz_gate
    assert decision1.policy_gate == decision2.policy_gate
    assert decision1.conformance_gate == decision2.conformance_gate
    # the evidence hash itself must be identical: the irrelevant lot was not
    # part of what got frozen into the snapshot
    assert decision1.evidence_hash == decision2.evidence_hash


def test_renamed_source_local_id_same_canonical_result(canonical_state):
    state = canonical_state

    # Baseline: propose directly against canonical warehouse id WH-B.
    baseline_state, baseline_decision = propose_transfer(
        state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID
    )

    # Now simulate a source system that calls WH-B by a different
    # source-local name ("WMS-LOC-B"), with an identity mapping recorded
    # (docs/experiment/spec/02_scope_and_non_goals.md "Semantic identity
    # alignment"). Resolving through the mapping before propose_transfer
    # must give the identical canonical decision.
    mapped_state, _ = add_id_mapping(state, "WMS-LOC-B", WH_B)
    resolved_source = resolve_id(mapped_state, "WMS-LOC-B")
    assert resolved_source == WH_B

    mapped_state, mapped_decision = propose_transfer(
        mapped_state, "planner-1", resolved_source, WH_A, PART, 60, work_order_id=WO_ID
    )

    assert mapped_decision.status == baseline_decision.status == DECISION_APPROVED
    assert mapped_decision.evidence_hash == baseline_decision.evidence_hash
    assert mapped_decision.policy_gate == baseline_decision.policy_gate
    assert mapped_decision.authz_gate == baseline_decision.authz_gate
    assert mapped_decision.params["source_warehouse"] == baseline_decision.params["source_warehouse"]
