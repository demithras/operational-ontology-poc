"""Phase 10a item 1 — docs/experiment/spec/08_test_strategy.md "Stateful
testing" + "Differential testing": a Hypothesis RuleBasedStateMachine
driving the REAL live stack (never a fake/in-process double), differential-
compared against reference_model where the two are directly comparable
(pure inventory arithmetic), plus system invariants checked after every
convergence point.

## Scope (disclosed, not hidden — see tests/stateful/live_helpers.py's own
docstring for the two verbs deliberately left out: change_policy,
duplicate_cdc)

Rules implemented: supplier_delay/supplier_recovery (ERP), receive/
reserve/release inventory (WMS), propose/approve/execute/retry_execution
(decision_service), reschedule_work_order + a terminal-work-order variant
(MES — there is no live "cancel" HTTP endpoint in this repo, so the
"cancel" half of "reschedule/cancel work order" is covered by asserting
the real invariant a cancel target/terminal work order enforces: reschedule
on an already-DONE/CANCELLED seeded work order is always rejected),
change_permission (OpenFGA), restart_service (docker), delay_cdc (Kafka
Connect pause/resume). `restart_service`/`delay_cdc` are BUDGET-CAPPED to
fire at most once per machine instance — real infra restarts are too slow
to run unboundedly inside a Hypothesis loop.

## Differential design

`receive_inventory`/`reserve_inventory`/`release_inventory` call the REAL
reference_model.transitions functions of the same name (these need no
actor/policy/gate config at all — pure inventory arithmetic) against a
parallel `reference_model.state.WorldState`, then compare against the REAL
WMS's own `/inventory_lots` read for the SAME (part, warehouse) — this is
genuine A-vs-B differential testing per spec 08.

`execute_transfer`'s inventory EFFECT (source -= qty, destination += qty)
is mirrored using the exact same dataclass-replace formula reference_model.
transitions.execute_transfer applies internally (verified by reading its
source) rather than calling that function directly — `execute_transfer`
requires a fully-gated `Decision` object living inside the SAME
WorldState's `decisions` dict, which would mean replicating decision_
service's own authz/policy/evidence config (approval thresholds, safety
stock, exact contract version) just to get an oracle for a value the real
system computes completely independently. That gate-parity work was judged
not worth it for THIS property (H5's core "quantity arithmetic never goes
wrong", not "the gate reached the same verdict for the same made-up
reason") — `propose_transfer`/`approve_transfer` are exercised live and
their STRUCTURAL/immutability properties are checked as invariants, not
diffed against a re-derived gate verdict.

## Convergence bound

Every live-vs-reference comparison here reads WMS's own `/inventory_lots`
directly (not the hot projection) — WMS commits synchronously, so no wait
is needed for THIS specific comparison. Waiting for a decision to reach a
terminal execution status (needed before comparing execute_transfer's
effect) uses a DECLARED 25s bound (`_TERMINAL_TIMEOUT_S` below); exceeding
it is surfaced as an explicit `non_convergence` failure (08_test_strategy.md
"Differential testing": "if bound is exceeded, fail with non_convergence"),
never silently ignored.

## Bounded max_examples

Every rule call is a real HTTP round trip (and restart_service/delay_cdc
are real docker/Kafka-Connect operations), so this MUST stay small for a
local run: `max_examples=5, stateful_step_count=8` for the main machine
(~40 rule invocations total across ~14 rules, empirically 1-4 minutes
depending on how many land on execute_transfer's ~25s worst-case wait),
documented here per 08_test_strategy.md's own instruction to document the
bound.

**Honest coverage caveat**: with 14 eligible rules and only ~40 total
draws, an individual CI run of this exact budget is NOT guaranteed to
exercise every rule at least once (Hypothesis picks roughly uniformly
among eligible rules each step) — verified empirically during development:
an 8-example/6-step run of an EARLIER budget completed in 3.5s with zero
`propose_transfer` calls at all. This suite's real bug-finding burden for
the propose->approve->execute->retry chain specifically is carried by the
deliberately NARROWER `IdempotencyBugHuntMachine` below (5 rules only),
not by this 14-rule machine's small sample of a much larger space — see
that class's own docstring. A diagnostic run at max_examples=8/
stateful_step_count=10 (not committed, ~80 draws) reliably exercised
propose/approve/execute/retry and is what caught two real defects in this
suite's OWN differential-tracking code before either committed test ever
ran clean (see implementation-notes.md's Phase 10a item 1 section).
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg

import httpx
import pytest
from hypothesis import settings
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.decision_service import authz  # noqa: E402
from tests.integration.decision_helpers import set_inventory_and_wait, sku_to_canonical  # noqa: E402
from tests.stateful import live_helpers as lh  # noqa: E402
from reference_model import transitions as rtr  # noqa: E402
from reference_model.state import (  # noqa: E402
    Actor,
    PurchaseOrder,
    QUALITY_OK,
    ROLE_PLANNER,
    Warehouse,
    empty_state,
)

PART_SKU = "SKU-976101"
PART_CANONICAL = sku_to_canonical(PART_SKU)
WH_A, WH_B = "WH-A", "WH-B"
WAREHOUSES = [WH_A, WH_B]
REGION = "region-1"
AGENT_ID = "agent-stateful-1"

# Comfortably above default_safety_stock (10, contracts/policies/v1/data.json)
# so propose_transfer (always WH_A -> WH_B, see propose_transfer rules
# below) never spuriously DENIED_POLICYs on safety stock just because
# receive_inventory hasn't happened to run yet in a given example — found
# live during this test's own development: a fresh (0 on_hand) source with
# only a 1-in-14-rules chance per step of receive_inventory running first
# meant EVERY propose_transfer across an 80-step diagnostic run was
# DENIED_POLICY, and execute_transfer/retry_execution (this suite's most
# important rules) never ran at all — a silent, vacuous "pass".
SEED_ON_HAND = 100_000

_TERMINAL_TIMEOUT_S = 25.0
_TERMINAL_STATUSES = {"OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED", "ACTION_VERSION_INVALIDATED"}

QTY_SMALL = st.integers(min_value=1, max_value=15)


def _stack_up() -> bool:
    db_env.load_dotenv()
    try:
        r = httpx.get(f"{db_env.decision_service_url()}/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _stack_up(), reason="decision_service not reachable — run 'make up' first")


def _apply_transfer_effect_to_ref_state(ref_state, part: str, source: str, destination: str, qty: int):
    """Mirrors reference_model.transitions.execute_transfer's OWN inventory
    mutation (source on_hand -= qty; destination on_hand += qty, creating a
    fresh zero-reserved lot if none existed) — see this module's docstring
    for why the full gated function isn't called directly. Operates on the
    SAME `ref_state.inventory` dict receive_inventory/reserve_inventory/
    release_inventory already maintain (a single unified ledger — an
    earlier version of this file used a SEPARATE dict for this one effect
    and it silently desynced from the receive/reserve/release history,
    caught before commit by re-reading this file end to end)."""
    from reference_model.state import InventoryLot

    inventory = dict(ref_state.inventory)
    src_key = (part, source)
    src_lot = inventory.get(src_key)
    if src_lot is None:
        src_lot = InventoryLot(lot_id=f"LOT-{source}-{part}", part=part, warehouse=source, on_hand=0, reserved=0, quality_status=QUALITY_OK, as_of=ref_state.clock)
    inventory[src_key] = replace(src_lot, on_hand=src_lot.on_hand - qty, as_of=ref_state.clock)

    dst_key = (part, destination)
    dst_lot = inventory.get(dst_key)
    if dst_lot is None:
        dst_lot = InventoryLot(lot_id=f"LOT-{destination}-{part}", part=part, warehouse=destination, on_hand=qty, reserved=0, quality_status=QUALITY_OK, as_of=ref_state.clock)
    else:
        dst_lot = replace(dst_lot, on_hand=dst_lot.on_hand + qty, as_of=ref_state.clock)
    inventory[dst_key] = dst_lot

    return replace(ref_state, inventory=inventory)


class _LiveStackMachine(RuleBasedStateMachine):
    """Shared setup/teardown + plain (non-@rule) action bodies. Subclasses
    define their OWN @rule set — Hypothesis collects rules from the class
    actually instantiated, so a narrower subclass with fewer @rule methods
    genuinely runs a smaller universe (used by the bug-hunt machine below
    to make finding the injected bug fast and reliable)."""

    def __init__(self):
        super().__init__()
        db_env.load_dotenv()
        base_urls = db_env.http_base_urls()
        timeout = httpx.Timeout(15.0)
        self.decision_client = httpx.Client(base_url=db_env.decision_service_url(), timeout=timeout)
        self.wms_client = httpx.Client(base_url=base_urls["wms"], timeout=timeout)
        self.mes_client = httpx.Client(base_url=base_urls["mes"], timeout=timeout)
        self.erp_client = httpx.Client(base_url=base_urls["erp"], timeout=timeout)
        self.openfga_api_url = db_env.openfga_api_url()
        self.openfga_store_id = authz.resolve_store_id(self.openfga_api_url)
        self.ontology_hot_conn = psycopg.connect(db_env.ontology_hot_dsn())

        warehouses = {w: Warehouse(w, REGION) for w in WAREHOUSES}
        actors = {"planner-1": Actor("planner-1", ROLE_PLANNER, frozenset({REGION}))}
        self.ref_state = empty_state(warehouses, actors, rtr.PolicyConfig(), clock=0)

        # Hypothesis instantiates a FRESH machine (fresh ref_state, always
        # starting at on_hand=0) per EXAMPLE, but WMS is a real external
        # system whose state persists across examples AND across separate
        # pytest invocations of this same test — found live (first run
        # after this reset was added was clean; the run immediately before
        # it failed 3/3 rules on exactly this desync, e.g. "assert 30 == 1"
        # where 30 was leftover from a PRIOR Hypothesis example's own
        # receive_inventory calls). Resetting the tracked lots to the exact
        # same on_hand=0/reserved=0 state ref_state starts at, at the top
        # of every machine instance, is what makes "fresh reference model"
        # and "real WMS" comparable from step one of every example.
        lh.set_lot(self.wms_client, PART_SKU, WH_B, on_hand=0, reserved=0)
        # WH_A specifically needs a GUARANTEED-sufficient, CDC-CONVERGED
        # starting balance before any propose_transfer call — see
        # SEED_ON_HAND's own comment for why. set_inventory_and_wait polls
        # the hot projection (not just WMS) until it actually reflects this
        # value, so decision_service's OWN evidence read sees it too, not
        # just a raw WMS row.
        set_inventory_and_wait(self.wms_client, self.ontology_hot_conn, PART_SKU, WH_A, on_hand=SEED_ON_HAND, reserved=0, timeout_s=40.0)

        # Mirror the SAME seeded starting state into ref_state so the
        # differential comparisons (receive/reserve/release/execute) start
        # from parity, not from ref_state's own empty default.
        from reference_model.state import InventoryLot

        self.ref_state = replace(
            self.ref_state,
            inventory={
                (PART_SKU, WH_A): InventoryLot(lot_id=f"LOT-{WH_A}-{PART_SKU}", part=PART_SKU, warehouse=WH_A, on_hand=SEED_ON_HAND, reserved=0, quality_status=QUALITY_OK, as_of=0),
                (PART_SKU, WH_B): InventoryLot(lot_id=f"LOT-{WH_B}-{PART_SKU}", part=PART_SKU, warehouse=WH_B, on_hand=0, reserved=0, quality_status=QUALITY_OK, as_of=0),
            },
        )

        self.decision_hashes: dict[str, str] = {}
        self.restart_budget = 1
        self.cdc_delay_budget = 1
        self.permission_granted = False

    def teardown(self):
        if self.permission_granted:
            lh.delete_grant_tuple(self.openfga_api_url, self.openfga_store_id, f"agent:{AGENT_ID}", "agent_grant", f"warehouse:{WH_B}")
        self.ontology_hot_conn.close()
        for client in (self.decision_client, self.wms_client, self.mes_client, self.erp_client):
            client.close()

    # -- shared action bodies (called from @rule wrappers) --------------------------

    def _do_receive_inventory(self, warehouse: str, qty: int) -> None:
        po_id = f"PO-STATEFUL-{uuid.uuid4().hex[:8]}"
        po = PurchaseOrder(po_id=po_id, part=PART_SKU, qty=qty, destination_warehouse=warehouse, expected_at=self.ref_state.clock + 1)
        new_pos = dict(self.ref_state.purchase_orders)
        new_pos[po_id] = po
        self.ref_state = replace(self.ref_state, purchase_orders=new_pos)
        self.ref_state, result = rtr.receive_inventory(self.ref_state, po_id, QUALITY_OK)
        assert result.ok, result

        lh.receive_inventory_live(self.wms_client, PART_SKU, warehouse, qty)

        ref_lot = self.ref_state.inventory[(PART_SKU, warehouse)]
        live_lot = lh.get_lot(self.wms_client, PART_SKU, warehouse)
        assert live_lot is not None
        assert live_lot["on_hand"] == ref_lot.on_hand, ("receive_inventory diverged", live_lot, ref_lot)

    def _do_reserve_inventory(self, warehouse: str, qty: int) -> None:
        ref_state_before = self.ref_state
        self.ref_state, ref_result = rtr.reserve_inventory(self.ref_state, PART_SKU, warehouse, qty)
        live_applied, live_lot_after = lh.reserve_inventory_live(self.wms_client, PART_SKU, warehouse, qty)
        assert ref_result.ok == live_applied, ("reserve_inventory ok-mismatch", ref_result, live_applied)
        if ref_result.ok:
            ref_lot = self.ref_state.inventory[(PART_SKU, warehouse)]
            assert live_lot_after["reserved"] == ref_lot.reserved, ("reserve_inventory diverged", live_lot_after, ref_lot)
        else:
            self.ref_state = ref_state_before

    def _do_release_inventory(self, warehouse: str, qty: int) -> None:
        ref_state_before = self.ref_state
        self.ref_state, ref_result = rtr.release_inventory(self.ref_state, PART_SKU, warehouse, qty)
        live_applied, live_lot_after = lh.release_inventory_live(self.wms_client, PART_SKU, warehouse, qty)
        assert ref_result.ok == live_applied, ("release_inventory ok-mismatch", ref_result, live_applied)
        if ref_result.ok:
            ref_lot = self.ref_state.inventory[(PART_SKU, warehouse)]
            assert live_lot_after["reserved"] == ref_lot.reserved, ("release_inventory diverged", live_lot_after, ref_lot)
        else:
            self.ref_state = ref_state_before

    def _do_propose(self, actor_id: str, source: str, destination: str, qty: int):
        decision = lh.propose_transfer_live(self.decision_client, actor_id, source, destination, PART_CANONICAL, qty)
        decision_id = decision.get("decision_id")
        print(f"[stateful] propose_transfer: actor={actor_id} qty={qty} -> status={decision.get('status')} decision_id={decision_id}")
        if decision_id:
            self.decision_hashes[decision_id] = decision.get("decision_content_hash")
        return decision

    def _do_approve(self, decision: dict):
        if decision.get("decision_id") is None:
            return decision
        return lh.approve_transfer_live(self.decision_client, decision, "supervisor-1")

    def _do_execute(self, decision: dict):
        decision_id = decision.get("decision_id")
        if decision_id is None:
            return
        # Hypothesis Bundle values are immutable — `decision` here is
        # whatever propose_transfer originally pushed, which may still say
        # "REQUIRES_APPROVAL" even after a LATER, separate approve_transfer
        # rule call approved it live. Re-fetch the REAL current status
        # rather than trusting the bundle's own stale copy (found while
        # reviewing this file before the first run: without this, a
        # decision that needed approval could never reach execute_transfer
        # at all, silently narrowing this rule to auto-approved decisions
        # only).
        current = lh.get_decision_live(self.decision_client, decision_id)
        if current["status"] != "APPROVED":
            return
        decision = current
        started = lh.execute_transfer_live(self.decision_client, decision_id)
        if started is None:
            return
        print(f"[stateful] execute_transfer: started {decision_id}, waiting up to {_TERMINAL_TIMEOUT_S}s for terminal status")
        final = self._wait_terminal(decision_id)
        assert final is not None, (
            f"non_convergence: decision {decision_id} never reached a terminal execution status "
            f"within the declared {_TERMINAL_TIMEOUT_S}s bound (08_test_strategy.md Differential testing: "
            f"'if bound is exceeded, fail with non_convergence')"
        )
        print(f"[stateful] execute_transfer: {decision_id} reached terminal status {final['status']}")
        if final["status"] != "OBSERVED_SUCCESS":
            return  # DIVERGED/OUTCOME_UNKNOWN/EXECUTION_FAILED: no expected-effect oracle to check here
        source = decision["parameters"]["source_warehouse"]
        destination = decision["parameters"]["destination_warehouse"]
        qty = decision["parameters"]["quantity"]
        self.ref_state = _apply_transfer_effect_to_ref_state(self.ref_state, PART_SKU, source, destination, qty)
        src_live = lh.get_lot(self.wms_client, PART_SKU, source)
        dst_live = lh.get_lot(self.wms_client, PART_SKU, destination)
        ref_src = self.ref_state.inventory[(PART_SKU, source)]
        ref_dst = self.ref_state.inventory[(PART_SKU, destination)]
        assert src_live["on_hand"] == ref_src.on_hand, ("execute source diverged", src_live, ref_src)
        assert dst_live["on_hand"] == ref_dst.on_hand, ("execute destination diverged", dst_live, ref_dst)
        print(f"[stateful] execute_transfer: differential check PASSED for {decision_id} (source={src_live}, dest={dst_live})")

    def _do_retry_execution(self, decision: dict) -> None:
        """H4/F10 ("one logical action creates at most one intended
        business effect"): retries at BOTH layers that could ever see a
        repeat call.

        (a) decision_service's own `/execute` again — Temporal's
        `start_workflow` with the SAME (deterministic, per-decision)
        workflow id raises WorkflowAlreadyStartedError and the existing
        handle is reused (services/decision_service/execution.py::
        start_or_get_execution) — so this call structurally CANNOT ever
        reach WMS a second time. Confirmed by reading that function's
        source before writing this rule (an earlier version of this file
        relied on THIS call alone to prove idempotency, which would have
        made the assertion vacuously true regardless of any real bug —
        the exact "green test that never runs the condition" trap).

        (b) the REAL retry surface: a direct `POST /transfers` to WMS
        itself with the EXACT SAME action_execution_id (deterministic from
        decision_id, services/decision_service/execution.py::
        action_execution_id_for) and body the original execution used —
        the same technique tests/integration/test_wms_idempotency.py
        already uses to prove this property, now driven from inside the
        stateful loop so Hypothesis can shrink a failing sequence. This is
        the retry that the WMS idempotency-disable toggle (tests/stateful's
        injected-bug proof) actually affects.
        """
        decision_id = decision.get("decision_id")
        if decision_id is None:
            return
        row = lh.get_decision_live(self.decision_client, decision_id)
        if row["status"] not in _TERMINAL_STATUSES:
            # Not executed yet at all — calling execute() now would be a
            # genuine FIRST execution, not a retry (a real effect IS
            # expected), so "before == after" would be the wrong check.
            return

        # (a) decision_service-level retry — must not error, status unchanged.
        lh.execute_transfer_live(self.decision_client, decision_id)
        row_after = lh.get_decision_live(self.decision_client, decision_id)
        assert row_after["status"] == row["status"], (
            "retry_execution via decision_service changed decision status", row["status"], row_after["status"],
        )

        # (b) WMS-level retry — the real idempotency surface.
        from services.decision_service.execution import action_execution_id_for

        action_execution_id = action_execution_id_for(decision_id)
        source = row["parameters"]["source_warehouse"]
        destination = row["parameters"]["destination_warehouse"]
        qty = row["parameters"]["quantity"]
        before_src = lh.get_lot(self.wms_client, PART_SKU, source)
        before_dst = lh.get_lot(self.wms_client, PART_SKU, destination)
        r = self.wms_client.post(
            "/transfers",
            json={
                "action_execution_id": action_execution_id, "source": source, "destination": destination,
                "part": PART_SKU, "quantity": qty,
            },
        )
        assert r.status_code in (200, 409), (
            f"unexpected status retrying WMS transfer for {action_execution_id}: {r.status_code} {r.text}"
        )
        after_src = lh.get_lot(self.wms_client, PART_SKU, source)
        after_dst = lh.get_lot(self.wms_client, PART_SKU, destination)
        assert before_src == after_src, ("WMS-level retry mutated source inventory (H4 violation)", before_src, after_src)
        assert before_dst == after_dst, ("WMS-level retry mutated destination inventory (H4 violation)", before_dst, after_dst)
        print(f"[stateful] retry_execution: WMS-level retry of {action_execution_id} (status {r.status_code}) left inventory unchanged — H4 holds")

    def _wait_terminal(self, decision_id: str) -> dict | None:
        deadline = time.monotonic() + _TERMINAL_TIMEOUT_S
        last = lh.get_decision_live(self.decision_client, decision_id)
        while time.monotonic() < deadline:
            if last["status"] in _TERMINAL_STATUSES:
                return last
            time.sleep(1.0)
            last = lh.get_decision_live(self.decision_client, decision_id)
        return None  # non_convergence — caller decides whether that's fatal

    # -- invariants (shared by every subclass) ---------------------------------------

    @invariant()
    def inventory_never_negative(self):
        for wh in WAREHOUSES:
            lot = lh.get_lot(self.wms_client, PART_SKU, wh)
            if lot is None:
                continue
            assert lot["on_hand"] >= 0, lot
            assert lot["reserved"] >= 0, lot
            assert lot["on_hand"] >= lot["reserved"], lot
            assert lot["available"] == lot["on_hand"] - lot["reserved"], lot

    @invariant()
    def decision_content_hash_immutable(self):
        for decision_id, first_hash in self.decision_hashes.items():
            row = lh.get_decision_live(self.decision_client, decision_id)
            assert row["decision_content_hash"] == first_hash, (
                f"decision {decision_id} content_hash changed: {first_hash} -> {row['decision_content_hash']}"
            )


class LiveTransferMachine(_LiveStackMachine):
    decisions = Bundle("decisions")

    @rule(warehouse=st.sampled_from(WAREHOUSES), qty=QTY_SMALL)
    def receive_inventory(self, warehouse, qty):
        self._do_receive_inventory(warehouse, qty)

    @rule(warehouse=st.sampled_from(WAREHOUSES), qty=QTY_SMALL)
    def reserve_inventory(self, warehouse, qty):
        self._do_reserve_inventory(warehouse, qty)

    @rule(warehouse=st.sampled_from(WAREHOUSES), qty=QTY_SMALL)
    def release_inventory(self, warehouse, qty):
        self._do_release_inventory(warehouse, qty)

    @rule(target=decisions, actor_id=st.sampled_from(["planner-1", "junior-1"]), qty=QTY_SMALL)
    def propose_transfer(self, actor_id, qty):
        return self._do_propose(actor_id, WH_A, WH_B, qty)

    @rule(decision=decisions)
    def approve_transfer(self, decision):
        self._do_approve(decision)

    @rule(decision=decisions)
    def execute_transfer(self, decision):
        self._do_execute(decision)

    @rule(decision=decisions)
    def retry_execution(self, decision):
        self._do_retry_execution(decision)

    @rule()
    def reschedule_work_order(self):
        wo_id = lh.pick_work_order(self.mes_client, "PLANNED") or lh.pick_work_order(self.mes_client, "RELEASED")
        if wo_id is None:
            return
        r = lh.reschedule_work_order_live(self.mes_client, wo_id, new_planned_start=999999)
        assert r.status_code in (200, 409), r.text

    @rule()
    def attempt_reschedule_terminal_work_order(self):
        wo_id = lh.pick_work_order(self.mes_client, "DONE") or lh.pick_work_order(self.mes_client, "CANCELLED")
        if wo_id is None:
            return
        r = lh.reschedule_work_order_live(self.mes_client, wo_id, new_planned_start=999999)
        assert r.status_code == 409, (
            f"H5 invariant violated: reschedule on a terminal work order {wo_id} returned {r.status_code}, expected 409"
        )

    @rule()
    def supplier_delay(self):
        po_id = lh.pick_purchase_order(self.erp_client, "OPEN")
        if po_id is None:
            return
        r = lh.supplier_delay_live(self.erp_client, po_id, new_expected_at=999999, reason="stateful-suite delay")
        assert r.status_code in (200, 409), r.text

    @rule()
    def supplier_recovery(self):
        po_id = lh.pick_purchase_order(self.erp_client, "DELAYED")
        if po_id is None:
            return
        r = lh.supplier_recovery_live(self.erp_client, po_id, action_execution_id=f"ae-stateful-{uuid.uuid4().hex[:8]}")
        assert r.status_code in (200, 409), r.text

    @rule()
    def change_permission(self):
        object_ = f"warehouse:{WH_B}"
        user = f"agent:{AGENT_ID}"
        if not self.permission_granted:
            lh.write_grant_tuple(self.openfga_api_url, self.openfga_store_id, user, "agent_grant", object_)
            self.permission_granted = True
            check = authz.check(self.openfga_api_url, self.openfga_store_id, "can_transfer_inventory", object_, "agent", AGENT_ID)
            assert check.allowed, ("change_permission grant did not take effect live", check)
        else:
            lh.delete_grant_tuple(self.openfga_api_url, self.openfga_store_id, user, "agent_grant", object_)
            self.permission_granted = False
            check = authz.check(self.openfga_api_url, self.openfga_store_id, "can_transfer_inventory", object_, "agent", AGENT_ID)
            assert not check.allowed, ("change_permission revoke did not take effect live", check)

    @rule()
    def restart_service(self):
        if self.restart_budget <= 0:
            return
        self.restart_budget -= 1
        # projection_builder's health port isn't one of the propose-path
        # services db_env.http_base_urls() exposes — read it directly from
        # the same .env this module already loaded via db_env.load_dotenv().
        health_port = os.environ.get("PROJECTION_BUILDER_HEALTH_PORT", "15485")
        recovered = lh.restart_service_live("projection_builder", f"http://localhost:{health_port}/health")
        assert recovered, "projection_builder did not recover after restart within the budgeted timeout"

    @rule()
    def delay_cdc(self):
        if self.cdc_delay_budget <= 0:
            return
        self.cdc_delay_budget -= 1
        connect_url = db_env.connect_rest_url()
        paused = lh.pause_wms_connector(connect_url)
        if not paused:
            return
        time.sleep(3.0)
        resumed = lh.resume_wms_connector(connect_url)
        assert resumed, "WMS Debezium connector did not resume after delay_cdc"


def test_live_transfer_machine_holds_invariants():
    """The main entry point. Bounded per this module's own docstring:
    max_examples=5, stateful_step_count=8 (~40 real rule invocations);
    see the module docstring's "Honest coverage caveat" for what that
    bound does and does not guarantee."""
    from hypothesis.stateful import run_state_machine_as_test

    run_state_machine_as_test(LiveTransferMachine, settings=settings(max_examples=5, stateful_step_count=8, deadline=None))


# -- Injected-bug proof (docs/experiment/briefs/phase10a.md item 1: "Confirm
# Hypothesis finds + shrinks at least one deliberately injected failure ...
# e.g. a test-mode flag disabling the WMS idempotency check") -------------


class IdempotencyBugHuntMachine(_LiveStackMachine):
    """A DELIBERATELY TIGHT machine: ONE rule that runs the WHOLE
    propose -> approve -> execute -> WMS-level-retry chain every single
    step, rather than the Bundle-based multi-rule design (propose_transfer/
    approve_transfer/execute_transfer/retry_execution as 4 separate rules
    Hypothesis draws independently) LiveTransferMachine above uses.

    That Bundle-based shape was tried FIRST for this class too and proved
    unreliable even at 15 examples x 8 steps (120 total draws): retry_
    execution only ever fires usefully when it happens to re-draw a
    bundle entry that some EARLIER execute_transfer draw already turned
    terminal, and with ~13 proposals accumulating per example against 1-4
    actual executions, that compound-probability draw never landed once in
    120 tries — confirmed live (see implementation-notes.md's Phase 10a
    item 1 section). Collapsing the whole chain into one rule makes EVERY
    step a genuine attempt at the exact scenario the injected bug lives in,
    which is what "confirm Hypothesis finds + shrinks" actually needs —
    Hypothesis still varies `qty` (and shrinks it to a minimal failing
    value) across whichever step first hits a real OBSERVED_SUCCESS."""

    @rule(qty=QTY_SMALL)
    def propose_approve_execute_and_retry(self, qty):
        decision = self._do_propose("planner-1", WH_A, WH_B, qty)
        decision = self._do_approve(decision)
        self._do_execute(decision)
        self._do_retry_execution(decision)


def test_stateful_finds_and_shrinks_disabled_idempotency_bug():
    """Arms the REAL test-mode idempotency-disable toggle (services/
    common/faults.py::FaultRegistry, via WMS's own POST /_test/idempotency-
    check — see services/wms/transfers.py's comment for why this is the
    real mechanism rather than a source edit) on the REAL running WMS
    service, then runs IdempotencyBugHuntMachine expecting Hypothesis to
    find a real H4 violation (a retry mutating inventory again) and print a
    minimal shrunk reproduction. Always disarms the toggle afterward, pass
    or fail, so no other test in this session ever runs against a broken
    WMS."""
    db_env.load_dotenv()
    wms_url = db_env.http_base_urls()["wms"]
    r = httpx.post(f"{wms_url}/_test/idempotency-check", json={"enabled": False}, timeout=10.0)
    r.raise_for_status()
    assert r.json()["idempotency_check_enabled"] is False, r.json()

    import contextlib
    import io

    from hypothesis.stateful import run_state_machine_as_test

    buf = io.StringIO()
    raised: AssertionError | None = None
    try:
        with contextlib.redirect_stdout(buf):
            try:
                run_state_machine_as_test(
                    IdempotencyBugHuntMachine,
                    settings=settings(max_examples=15, stateful_step_count=6, deadline=None, print_blob=True),
                )
            except AssertionError as exc:  # noqa: BLE001 - deliberately broad: this IS the expected outcome
                raised = exc
    finally:
        r2 = httpx.post(f"{wms_url}/_test/idempotency-check", json={"enabled": True}, timeout=10.0)
        r2.raise_for_status()
        assert r2.json()["idempotency_check_enabled"] is True, r2.json()

    output = buf.getvalue()
    print(output)  # always visible in the test's own output, pass or fail
    assert raised is not None, (
        "Hypothesis did NOT find the injected idempotency bug within the budgeted examples — "
        "expected a real H4 violation (a WMS-level retry re-applying its inventory mutation). "
        f"Captured run output:\n{output[-3000:]}"
    )
    # Hypothesis 6.x (Python 3.11+) attaches the shrunk falsifying example as
    # an exception NOTE (PEP 678 add_note) rather than printing "Falsifying
    # example" to stdout when driven via run_state_machine_as_test outside
    # pytest's own collection hook — found live: the stateful reporter's
    # actual header text is "Failing test case:" (followed by the exact
    # minimal rule/argument sequence to reproduce), not the plain-@given
    # reporter's "Falsifying example:" text this test originally checked
    # for, which is why the first version failed its own "did it shrink"
    # check even though Hypothesis genuinely had shrunk to qty=1.
    notes = "\n".join(getattr(raised, "__notes__", []) or [])
    combined = output + "\n" + notes
    assert "Failing test case:" in combined and "propose_approve_execute_and_retry" in combined, (
        "Hypothesis raised an AssertionError but neither stdout nor the exception's own notes "
        f"contain a shrunk minimal reproduction. stdout:\n{output[-2000:]}\nnotes:\n{notes}"
    )
    print(f"[bug-hunt] Hypothesis found and shrunk the injected bug.\nException: {raised}\nNotes:\n{notes}")
