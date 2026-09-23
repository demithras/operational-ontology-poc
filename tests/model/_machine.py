"""Shared Hypothesis RuleBasedStateMachine factory for the pure reference
model — docs/experiment/spec/08_test_strategy.md "Stateful testing".

Rules cover every verb from 08's example list that applies to a pure model:

    supplier_delay, supplier_recovery, receive_inventory, reserve_inventory,
    release_inventory, propose_transfer, approve_transfer (approve_decision),
    execute_transfer, retry_execution (execute_transfer again with the same
    derived key), reschedule_work_order, cancel_work_order,
    change_permission, change_policy

`restart_service`, `delay_cdc`, and `duplicate_cdc` are skipped here — they
require a real process boundary / CDC pipeline and belong to Phase 6
(docs/experiment/spec/12_implementation_plan.md), not the Phase 1 pure
model (docs/adr/0001-lite-mode-for-phase-1.md).

`make_machine(bugs)` returns a fresh RuleBasedStateMachine subclass with the
given bug set baked in, so the SAME rule set can be run clean
(tests/model/test_stateful.py) or with exactly one bug injected
(tests/model/test_bug_detection.py).
"""

from __future__ import annotations

from dataclasses import replace

from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from reference_model import transitions as tr
from reference_model.invariants import check_invariants, expected_authz_gate_status, expected_policy_gate_status
from reference_model.state import (
    Actor,
    Bugs,
    InventoryLot,
    NO_BUGS,
    PolicyConfig,
    PurchaseOrder,
    QUALITY_OK,
    QUALITY_QUARANTINE,
    ROLE_AGENT,
    ROLE_JUNIOR_PLANNER,
    ROLE_PLANNER,
    ROLE_SUPERVISOR,
    ROLES,
    WO_PLANNED,
    Warehouse,
    WorkOrder,
    empty_state,
)

PART = "PX-1"
WH_1 = "WH-1"
WH_2 = "WH-2"
WAREHOUSES = [WH_1, WH_2]
REGION = "region-1"

# actor_id -> (role, regions, task_grants)
ACTOR_SPECS = {
    "planner-1": (ROLE_PLANNER, frozenset({REGION}), frozenset()),
    "junior-1": (ROLE_JUNIOR_PLANNER, frozenset({REGION}), frozenset()),
    "supervisor-1": (ROLE_SUPERVISOR, frozenset({REGION}), frozenset()),
    "agent-1": (ROLE_AGENT, frozenset({REGION}), frozenset()),
    "agent-granted-1": (ROLE_AGENT, frozenset({REGION}), frozenset({"transfer_inventory"})),
}

PO_IDS = ["PO-1", "PO-2"]
WO_IDS = ["WO-1"]

QTY_STRATEGY = st.one_of(
    st.integers(min_value=1, max_value=250),
    # explicit boundary-biased values so Hypothesis reliably explores the
    # transfer_approval_threshold_units edge (100), and the ~80-unit
    # neighborhood that lets two independently-valid transfers combine to
    # exceed available stock (the canonical 100/80/80 race from
    # docs/experiment/spec/09_failure_and_adversarial_matrix.md), even
    # though both are thin slices of the full integer range.
    st.sampled_from([1, 10, 50, 79, 80, 81, 99, 100, 101, 150, 250]),
)


def make_machine(bugs: Bugs = NO_BUGS, name: str = "TransferMachine") -> type:
    """Build a fresh RuleBasedStateMachine subclass with `bugs` baked into
    every call that accepts a bug set. A fresh class is required (rather
    than a shared mutable attribute) because Hypothesis inspects the class
    object itself when collecting rules."""

    class _TransferMachine(RuleBasedStateMachine):
        BUGS: Bugs = bugs

        decisions = Bundle("decisions")

        def __init__(self):
            super().__init__()
            warehouses = {w: Warehouse(w, REGION) for w in WAREHOUSES}
            actors = {
                aid: Actor(aid, role, regions, grants)
                for aid, (role, regions, grants) in ACTOR_SPECS.items()
            }
            policy = PolicyConfig(
                transfer_approval_threshold_units=100,
                safety_stock={(PART, w): 5 for w in WAREHOUSES},
                max_evidence_freshness_s=5,
            )
            state = empty_state(warehouses, actors, policy, clock=0)
            state = replace(
                state,
                # 150 on_hand + safety_stock 5 means two independently-valid
                # 80-unit transfers (each individually leaves 70 >= 5 at
                # proposal time) can still combine to a 160-unit total draw
                # against 150 available at execution time — this is what
                # makes the classic 100/80/80 concurrency race
                # (docs/experiment/spec/09_failure_and_adversarial_matrix.md)
                # reachable by the stateful machine without also requiring a
                # REQUIRES_APPROVAL/approve_transfer detour.
                inventory={
                    (PART, w): InventoryLot(f"LOT-{w}", PART, w, 150, 0, QUALITY_OK, as_of=0)
                    for w in WAREHOUSES
                },
                purchase_orders={
                    "PO-1": PurchaseOrder("PO-1", PART, 50, WH_1, expected_at=100),
                    "PO-2": PurchaseOrder("PO-2", PART, 50, WH_2, expected_at=100),
                },
                work_orders={
                    "WO-1": WorkOrder("WO-1", WO_PLANNED, "HIGH", 100, WH_1, {PART: 40}),
                },
            )
            self.state = state

        # -- propose / approve / execute -------------------------------------------------

        @rule(
            target=decisions,
            actor=st.sampled_from(list(ACTOR_SPECS)),
            src=st.sampled_from(WAREHOUSES),
            dst=st.sampled_from(WAREHOUSES),
            qty=QTY_STRATEGY,
        )
        def propose_transfer(self, actor, src, dst, qty):
            pre_authz = expected_authz_gate_status(self.state.actors[actor], self.state.warehouses[src], "transfer_inventory")
            self.state, decision = tr.propose_transfer(
                self.state, actor, src, dst, PART, qty, bugs=self.BUGS
            )
            # Oracle cross-checks. These run UNCONDITIONALLY (they never
            # consult self.BUGS) — that is what lets them catch a bug when
            # it is active: reference_model.invariants.expected_authz_gate_status
            # and expected_policy_gate_status hard-code the CORRECT rule, so
            # a real mismatch between the actual gate result and the oracle
            # is itself the failure Hypothesis is supposed to find.
            if decision.evidence_gate is not None and decision.evidence_gate.status == "ALLOW":
                assert decision.authz_gate.status == pre_authz, (
                    f"authz_gate mismatch: recorded={decision.authz_gate.status} "
                    f"expected={pre_authz} actor={actor} src={src}"
                )
            if (
                decision.authz_gate is not None
                and decision.authz_gate.status == "ALLOW"
                and decision.policy_gate is not None
                and decision.policy_gate.status in ("ALLOW", "REQUIRES_APPROVAL")
            ):
                expected = expected_policy_gate_status(qty, self.state.policy_config.transfer_approval_threshold_units)
                assert decision.policy_gate.status == expected, (
                    f"policy_gate mismatch: recorded={decision.policy_gate.status} "
                    f"expected={expected} qty={qty}"
                )
            return decision.decision_id

        @rule(decision_id=decisions, approver=st.sampled_from(["supervisor-1", "planner-1", "junior-1"]))
        def approve_transfer(self, decision_id, approver):
            decision = self.state.decisions.get(decision_id)
            if decision is None:
                return
            self.state, _result = tr.approve_decision(
                self.state, decision_id, approver, decision.content_hash
            )

        @rule(decision_id=decisions)
        def execute_transfer(self, decision_id):
            if decision_id not in self.state.decisions:
                return
            key = f"idem-{decision_id}"
            self.state, _result = tr.execute_transfer(self.state, decision_id, key, bugs=self.BUGS)

        @rule(decision_id=decisions)
        def retry_execution(self, decision_id):
            # Immediately re-send the SAME logical execution with the SAME
            # derived idempotency key, back to back
            # (docs/experiment/spec/08_test_strategy.md "Idempotency tests":
            # "send twice sequentially"). This must never create a second
            # business effect
            # (docs/experiment/spec/06_decision_and_action_runtime.md
            # "Exactly-once language"). Doing both calls inside one rule
            # (rather than relying on the Bundle happening to reselect the
            # same decision_id across two separate rule applications) makes
            # the retry scenario reliably reachable for Hypothesis.
            if decision_id not in self.state.decisions:
                return
            key = f"idem-{decision_id}"
            self.state, _result1 = tr.execute_transfer(self.state, decision_id, key, bugs=self.BUGS)
            self.state, _result2 = tr.execute_transfer(self.state, decision_id, key, bugs=self.BUGS)

        @rule(
            target=decisions,
            actor=st.sampled_from(list(ACTOR_SPECS)),
            warehouse=st.sampled_from(WAREHOUSES),
            dst=st.sampled_from(WAREHOUSES),
            qty1=QTY_STRATEGY,
            qty2=QTY_STRATEGY,
        )
        def concurrent_transfer_race(self, actor, warehouse, dst, qty1, qty2):
            # The canonical concurrency race
            # (docs/experiment/spec/09_failure_and_adversarial_matrix.md
            # "Concurrency tests" / docs/experiment/spec/01_hypotheses.md
            # H5): two decisions proposed from the SAME evidence (before
            # either executes) may both be individually valid, yet their
            # combined quantity can exceed what is actually available by
            # the time both try to execute. Encoded as one atomic rule (like
            # retry_execution above) so Hypothesis reliably reaches the
            # propose-propose-execute-execute ordering that this bug
            # depends on, instead of relying on it falling out of 11
            # independently-scheduled rules by chance.
            self.state, decision_a = tr.propose_transfer(
                self.state, actor, warehouse, dst, PART, qty1, bugs=self.BUGS
            )
            self.state, decision_b = tr.propose_transfer(
                self.state, actor, warehouse, dst, PART, qty2, bugs=self.BUGS
            )
            if decision_a.status == "APPROVED":
                self.state, _ = tr.execute_transfer(
                    self.state, decision_a.decision_id, f"idem-{decision_a.decision_id}", bugs=self.BUGS
                )
            if decision_b.status == "APPROVED":
                self.state, _ = tr.execute_transfer(
                    self.state, decision_b.decision_id, f"idem-{decision_b.decision_id}", bugs=self.BUGS
                )
            return decision_b.decision_id

        # -- supply / inventory -------------------------------------------------

        @rule(po_id=st.sampled_from(PO_IDS), new_expected_at=st.integers(min_value=0, max_value=400))
        def supplier_delay(self, po_id, new_expected_at):
            self.state, _result = tr.supplier_delay(self.state, po_id, new_expected_at, "transport_delay")

        @rule(po_id=st.sampled_from(PO_IDS), expected_at=st.integers(min_value=0, max_value=400))
        def supplier_recovery(self, po_id, expected_at):
            self.state, _result = tr.supplier_recovery(self.state, po_id, expected_at)

        @rule(po_id=st.sampled_from(PO_IDS), quality=st.sampled_from([QUALITY_OK, QUALITY_QUARANTINE]))
        def receive_inventory(self, po_id, quality):
            self.state, _result = tr.receive_inventory(self.state, po_id, quality_status=quality)

        @rule(warehouse=st.sampled_from(WAREHOUSES), qty=st.integers(min_value=1, max_value=50))
        def reserve_inventory(self, warehouse, qty):
            self.state, _result = tr.reserve_inventory(self.state, PART, warehouse, qty)

        @rule(warehouse=st.sampled_from(WAREHOUSES), qty=st.integers(min_value=1, max_value=50))
        def release_inventory(self, warehouse, qty):
            self.state, _result = tr.release_inventory(self.state, PART, warehouse, qty)

        # -- work orders -------------------------------------------------

        @rule(work_order_id=st.sampled_from(WO_IDS), new_planned_start=st.integers(min_value=0, max_value=400))
        def reschedule_work_order(self, work_order_id, new_planned_start):
            self.state, _result = tr.reschedule_work_order(self.state, work_order_id, new_planned_start)

        @rule(work_order_id=st.sampled_from(WO_IDS))
        def cancel_work_order(self, work_order_id):
            self.state, _result = tr.cancel_work_order(self.state, work_order_id)

        # -- governance -------------------------------------------------

        @rule(actor_id=st.sampled_from(list(ACTOR_SPECS)), role=st.sampled_from(sorted(ROLES)))
        def change_permission(self, actor_id, role):
            self.state, _result = tr.change_permission(self.state, actor_id, role=role)

        @rule(
            threshold=st.integers(min_value=50, max_value=200),
            safety_stock_qty=st.integers(min_value=0, max_value=60),
        )
        def change_policy(self, threshold, safety_stock_qty):
            new_policy = PolicyConfig(
                transfer_approval_threshold_units=threshold,
                safety_stock={(PART, w): safety_stock_qty for w in WAREHOUSES},
                max_evidence_freshness_s=self.state.policy_config.max_evidence_freshness_s,
            )
            self.state, _result = tr.change_policy(self.state, new_policy)

        @rule(delta=st.integers(min_value=0, max_value=10))
        def advance_clock(self, delta):
            self.state, _result = tr.advance_clock(self.state, delta)

        # -- invariants, checked after every step -------------------------------------------------

        @invariant()
        def invariants_hold(self):
            violations = check_invariants(self.state)
            assert not violations, "invariant violation(s): " + "; ".join(violations)

    _TransferMachine.__name__ = name
    _TransferMachine.__qualname__ = name
    return _TransferMachine
