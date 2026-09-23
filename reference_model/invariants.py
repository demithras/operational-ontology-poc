"""Domain invariants for the pure reference model.

`check_invariants(state)` performs single-state structural checks
(docs/experiment/spec/03_domain_scenario.md "State-machine invariants",
docs/experiment/spec/01_hypotheses.md H5). It never needs a prior state.

The `expected_*` functions below are independent oracles for gate outcomes:
they hard-code the CORRECT spec rule (never consulting `Bugs`) so that a
mutated/bugged transition can be caught by comparing what a `Decision`
actually recorded against what these functions say it should have recorded.
This is what makes `tests/model/test_bug_detection.py` able to make
Hypothesis fail deliberately when a bug flag changes real behavior without
changing these oracle functions.
"""

from __future__ import annotations

from typing import List

from reference_model.state import (
    DECISION_NO_EFFECT_STATUSES,
    GATE_ALLOW,
    GATE_DENY,
    GATE_REQUIRES_APPROVAL,
    QUALITY_STATUSES,
    ROLE_AGENT,
    ROLE_JUNIOR_PLANNER,
    ROLE_PLANNER,
    ROLE_SUPERVISOR,
    WORK_ORDER_STATUSES,
    Actor,
    Warehouse,
    WorldState,
)
from reference_model.transitions import compute_pinned_hash


def check_invariants(state: WorldState) -> List[str]:
    """Return a list of human-readable violation descriptions. Empty list
    means the state is internally consistent."""
    violations: List[str] = []

    # InventoryLot invariants (docs/experiment/spec/03_domain_scenario.md).
    for key, lot in state.inventory.items():
        if lot.reserved < 0:
            violations.append(f"lot {key}: reserved < 0 ({lot.reserved})")
        if lot.on_hand < lot.reserved:
            violations.append(f"lot {key}: on_hand ({lot.on_hand}) < reserved ({lot.reserved})")
        if lot.available < 0:
            violations.append(f"lot {key}: available < 0 ({lot.available})")
        if lot.quality_status not in QUALITY_STATUSES:
            violations.append(f"lot {key}: unknown quality_status {lot.quality_status!r}")

    # WorkOrder status vocabulary.
    for wo_id, wo in state.work_orders.items():
        if wo.status not in WORK_ORDER_STATUSES:
            violations.append(f"work order {wo_id}: unknown status {wo.status!r}")

    # ActionExecution.idempotencyKey unique per logical action.
    keys = [e.idempotency_key for e in state.transfer_effects]
    if len(keys) != len(set(keys)):
        dupes = {k for k in keys if keys.count(k) > 1}
        violations.append(f"duplicate idempotency keys applied: {sorted(dupes)}")

    # applied_idempotency_keys must exactly track effect keys (no phantom
    # bookkeeping, no missing bookkeeping).
    if set(keys) != set(state.applied_idempotency_keys):
        violations.append(
            "applied_idempotency_keys out of sync with transfer_effects: "
            f"effects={sorted(set(keys))} tracked={sorted(state.applied_idempotency_keys)}"
        )

    # Decision-level invariants.
    for decision_id, decision in state.decisions.items():
        # No effect without an APPROVED decision whose gates all passed:
        # denial/pending statuses must carry zero execution/outcome.
        if decision.status in DECISION_NO_EFFECT_STATUSES:
            if decision.execution_id is not None:
                violations.append(
                    f"decision {decision_id}: status {decision.status} has execution_id set"
                )
            if decision.outcome_id is not None:
                violations.append(
                    f"decision {decision_id}: status {decision.status} has outcome_id set"
                )

        # Approved decisions immutable: recomputed pinned-field hash must
        # match the stored content_hash regardless of current status.
        expected_hash = compute_pinned_hash(decision)
        if expected_hash != decision.content_hash:
            violations.append(
                f"decision {decision_id}: content_hash mismatch "
                f"(stored={decision.content_hash}, recomputed={expected_hash}) "
                "— pinned fields were mutated after creation"
            )

    return violations


def assert_invariants(state: WorldState) -> None:
    violations = check_invariants(state)
    assert not violations, "invariant violation(s): " + "; ".join(violations)


# ---------------------------------------------------------------------------
# Independent oracles (never consult Bugs) used to catch mutated/bugged
# gate behavior in tests/model/test_bug_detection.py.
# ---------------------------------------------------------------------------


def expected_policy_gate_status(quantity: int, threshold: int) -> str:
    """Correct rule from docs/experiment/spec/06_decision_and_action_runtime.md
    / the task's gate-order instructions: qty > threshold => REQUIRES_APPROVAL,
    else ALLOW (assuming safety-stock/quarantine checks already passed)."""
    return GATE_REQUIRES_APPROVAL if quantity > threshold else GATE_ALLOW


def expected_authz_gate_status(actor: Actor, source_warehouse: Warehouse, action_type: str) -> str:
    """Correct rule from docs/experiment/spec/03_domain_scenario.md
    "Authorization example" — independent of transitions.py's own
    (possibly bugged) implementation."""
    if action_type != "transfer_inventory":
        return GATE_ALLOW
    if actor.role == ROLE_JUNIOR_PLANNER:
        return GATE_DENY
    if actor.role in (ROLE_PLANNER, ROLE_SUPERVISOR):
        return GATE_ALLOW if source_warehouse.region in actor.regions else GATE_DENY
    if actor.role == ROLE_AGENT:
        has_grant = action_type in actor.task_grants
        in_region = source_warehouse.region in actor.regions
        return GATE_ALLOW if (has_grant and in_region) else GATE_DENY
    return GATE_DENY
