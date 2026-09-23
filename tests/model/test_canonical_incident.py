"""Canonical incident tests — docs/experiment/spec/03_domain_scenario.md.

Happy path plus every negative case listed under "Negative canonical
cases" in that document. Every negative case asserts zero external effects
(no ExecutionEffect created, applied_idempotency_keys unchanged, inventory
unchanged) — this is the Phase-1-testable slice of
docs/experiment/spec/01_hypotheses.md H2 ("0 side effects across the full
negative and adversarial suite").
"""

from __future__ import annotations

from dataclasses import replace

from reference_model.derive import derive
from reference_model.invariants import check_invariants
from reference_model.state import (
    DECISION_APPROVED,
    DECISION_DENIED_AUTHORIZATION,
    DECISION_DENIED_POLICY,
    DECISION_INSUFFICIENT_EVIDENCE,
    DECISION_INVALID_CONFORMANCE,
    DECISION_OBSERVED_SUCCESS,
    DECISION_REQUIRES_APPROVAL,
    QUALITY_OK,
    InventoryLot,
)
from reference_model.transitions import approve_decision, execute_transfer, propose_transfer

from .conftest import PART, WH_A, WH_B, WO_ID


def _no_effects(state_before, state_after):
    assert state_after.transfer_effects == state_before.transfer_effects
    assert state_after.applied_idempotency_keys == state_before.applied_idempotency_keys
    assert state_after.inventory == state_before.inventory


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_shortage_transfer_approve_execute(canonical_state):
    state = canonical_state

    risk = derive(state)
    assert risk[WO_ID].shortage == 60
    assert risk[WO_ID].at_risk is True

    state, decision = propose_transfer(
        state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID
    )
    assert decision.status == DECISION_APPROVED
    assert decision.evidence_gate.status == "ALLOW"
    assert decision.authz_gate.status == "ALLOW"
    assert decision.policy_gate.status == "ALLOW"
    assert decision.conformance_gate.status == "ALLOW"

    state, exec_result = execute_transfer(state, decision.decision_id, f"idem-{decision.decision_id}")
    assert exec_result.ok
    assert exec_result.status == DECISION_OBSERVED_SUCCESS

    outcome = state.outcomes[exec_result.outcome_id]
    assert outcome.status == DECISION_OBSERVED_SUCCESS

    risk_after = derive(state)
    assert risk_after[WO_ID].at_risk is False
    assert risk_after[WO_ID].shortage == 0

    assert not check_invariants(state)


# ---------------------------------------------------------------------------
# Negative case: stale evidence
# ---------------------------------------------------------------------------


def test_stale_evidence_yields_insufficient_evidence(canonical_state):
    state = canonical_state
    # push the clock far enough past the source lot's as_of that it exceeds
    # max_evidence_freshness_s (5s in this fixture's policy_config)
    state = replace(state, clock=state.clock + 30)

    before = state
    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    assert decision.status == DECISION_INSUFFICIENT_EVIDENCE
    assert decision.evidence_gate.status == "INSUFFICIENT_EVIDENCE"
    _no_effects(before, state)


# ---------------------------------------------------------------------------
# Negative case: junior planner (unauthorized actor)
# ---------------------------------------------------------------------------


def test_junior_planner_denied_authorization(canonical_state):
    state = canonical_state
    before = state
    state, decision = propose_transfer(state, "junior-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    assert decision.status == DECISION_DENIED_AUTHORIZATION
    assert decision.authz_gate.status == "DENY"
    _no_effects(before, state)


def test_planner_outside_region_denied_authorization(canonical_state):
    state = canonical_state
    before = state
    state, decision = propose_transfer(
        state, "planner-outside-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID
    )

    assert decision.status == DECISION_DENIED_AUTHORIZATION
    _no_effects(before, state)


def test_agent_without_task_grant_denied_authorization(canonical_state):
    state = canonical_state
    before = state
    state, decision = propose_transfer(state, "agent-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    assert decision.status == DECISION_DENIED_AUTHORIZATION
    _no_effects(before, state)


def test_agent_with_exact_task_grant_is_authorized(canonical_state):
    state = canonical_state
    state, decision = propose_transfer(
        state, "agent-granted-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID
    )
    assert decision.authz_gate.status == "ALLOW"
    assert decision.status == DECISION_APPROVED


# ---------------------------------------------------------------------------
# Negative case: safety-stock breach
# ---------------------------------------------------------------------------


def test_safety_stock_breach_denied_policy(canonical_state):
    state = canonical_state
    before = state
    # WH-B has 140 on hand, safety stock 50 -> max safe transfer is 90.
    # Requesting 100 would leave 40 < 50, breaching safety stock.
    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 100, work_order_id=WO_ID)

    assert decision.status == DECISION_DENIED_POLICY
    assert decision.policy_gate.status == "DENY"
    _no_effects(before, state)


def test_quarantine_denied_policy(canonical_state):
    state = canonical_state
    quarantined = replace(state.inventory[(PART, WH_B)], quality_status="QUARANTINE")
    inv = dict(state.inventory)
    inv[(PART, WH_B)] = quarantined
    state = replace(state, inventory=inv)
    before = state

    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 60, work_order_id=WO_ID)

    assert decision.status == DECISION_DENIED_POLICY
    _no_effects(before, state)


# ---------------------------------------------------------------------------
# Negative case: SHACL/conformance — missing policy version
# ---------------------------------------------------------------------------


def test_missing_policy_version_invalid_conformance(canonical_state):
    state = canonical_state
    before = state
    state, decision = propose_transfer(
        state,
        "planner-1",
        WH_B,
        WH_A,
        PART,
        60,
        work_order_id=WO_ID,
        omit_policy_version=True,
    )

    assert decision.status == DECISION_INVALID_CONFORMANCE
    assert decision.conformance_gate.status == "INVALID"
    _no_effects(before, state)


# ---------------------------------------------------------------------------
# Negative case: qty > 100 requires approval, cannot execute before approval
# ---------------------------------------------------------------------------


def test_qty_over_threshold_requires_approval_and_blocks_execution(canonical_state):
    state = canonical_state
    # give WH-B enough stock that a >100 transfer is otherwise policy-clean
    lot = replace(state.inventory[(PART, WH_B)], on_hand=500)
    inv = dict(state.inventory)
    inv[(PART, WH_B)] = lot
    state = replace(state, inventory=inv)

    before = state
    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 150, work_order_id=WO_ID)

    assert decision.status == DECISION_REQUIRES_APPROVAL
    assert decision.policy_gate.status == "REQUIRES_APPROVAL"
    _no_effects(before, state)

    # cannot execute before approval
    before2 = state
    state, exec_result = execute_transfer(state, decision.decision_id, f"idem-{decision.decision_id}")
    assert not exec_result.ok
    assert exec_result.status == "REJECTED_WRONG_STATE"
    _no_effects(before2, state)


# ---------------------------------------------------------------------------
# Negative case: approval replay on changed decision rejected
# ---------------------------------------------------------------------------


def test_approval_replay_on_changed_decision_rejected(canonical_state):
    state = canonical_state
    lot = replace(state.inventory[(PART, WH_B)], on_hand=500)
    inv = dict(state.inventory)
    inv[(PART, WH_B)] = lot
    state = replace(state, inventory=inv)

    state, decision = propose_transfer(state, "planner-1", WH_B, WH_A, PART, 150, work_order_id=WO_ID)
    assert decision.status == DECISION_REQUIRES_APPROVAL

    before = state
    wrong_hash = decision.content_hash + "tampered"
    state, approval_result = approve_decision(state, decision.decision_id, "supervisor-1", wrong_hash)

    assert not approval_result.ok
    assert approval_result.status == "REJECTED_HASH_MISMATCH"
    assert state.decisions[decision.decision_id].status == DECISION_REQUIRES_APPROVAL
    _no_effects(before, state)

    # correct hash succeeds
    state, approval_result_ok = approve_decision(
        state, decision.decision_id, "supervisor-1", decision.content_hash
    )
    assert approval_result_ok.ok
    assert state.decisions[decision.decision_id].status == DECISION_APPROVED
