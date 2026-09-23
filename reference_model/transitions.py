"""Pure state transitions for the operational-ontology POC reference model.

Every function here has the shape `transition(state, ...) -> (new_state, result)`
and never mutates its input `WorldState` or any object reachable from it —
each call builds fresh dataclass instances and fresh dict/tuple/frozenset
containers. This is Level 0 of docs/experiment/spec/08_test_strategy.md.

`propose_transfer` implements the gate pipeline described in
docs/experiment/spec/06_decision_and_action_runtime.md ("Proposal
algorithm"), in this exact order (see docs/adr/0001-lite-mode-for-phase-1.md
for why the order is evidence -> authorization -> policy -> conformance ->
APPROVED, matching 06's pseudocode with the evidence-freshness/closure check
prepended):

    1. freeze evidence snapshot (content hash of exact lots/policy/actor
       facts used)
    2. required-evidence check -> INSUFFICIENT_EVIDENCE if missing/stale
    3. authorization -> DENIED_AUTHORIZATION if denied
    4. policy -> DENIED_POLICY if denied; REQUIRES_APPROVAL if qty exceeds
       threshold (both terminal, matching 06's early-return semantics —
       conformance is not evaluated on these paths)
    5. conformance (SHACL-shaped) -> INVALID_CONFORMANCE if invalid
    6. APPROVED

Each gate result is stored SEPARATELY on the Decision (never collapsed into
one boolean), per docs/experiment/spec/01_hypotheses.md H1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Tuple

from reference_model.state import (
    ALL_BUGS,
    BUG_POLICY_THRESHOLD_LT,
    BUG_SKIP_AUTHZ,
    BUG_SKIP_EXECUTION_RECHECK,
    BUG_SKIP_IDEMPOTENCY,
    Bugs,
    DECISION_APPROVED,
    DECISION_DENIED_AUTHORIZATION,
    DECISION_DENIED_POLICY,
    DECISION_INSUFFICIENT_EVIDENCE,
    DECISION_INVALID_CONFORMANCE,
    DECISION_OBSERVED_SUCCESS,
    DECISION_REQUIRES_APPROVAL,
    Decision,
    EvidenceItem,
    EvidenceSnapshot,
    ExecutionEffect,
    GATE_ALLOW,
    GATE_DENY,
    GATE_INSUFFICIENT_EVIDENCE,
    GATE_INVALID,
    GATE_REQUIRES_APPROVAL,
    GateResult,
    NO_BUGS,
    Outcome,
    PO_CANCELLED,
    PO_DELAYED,
    PO_OPEN,
    PO_RECEIVED,
    PolicyConfig,
    PurchaseOrder,
    QUALITY_OK,
    QUALITY_QUARANTINE,
    ROLE_AGENT,
    ROLE_JUNIOR_PLANNER,
    ROLE_PLANNER,
    ROLE_SUPERVISOR,
    Approval,
    WO_CANCELLED,
    WO_DONE,
    WORK_ORDER_TERMINAL_STATUSES,
    WorkOrder,
    WorldState,
)

CONTRACT_VERSIONS_DEFAULT = {
    "ontology_version": "v1",
    "shape_set_version": "1",
    "authz_model_version": "1",
    "policy_bundle_version": "1",
}

ACTION_TRANSFER_INVENTORY = "transfer_inventory"
ACTION_TRANSFER_INVENTORY_VERSION = 3  # mirrors 05_ontology_and_contracts.md example


# ---------------------------------------------------------------------------
# Generic transition result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    ok: bool
    status: str
    message: str = ""
    ref: Optional[str] = None


@dataclass(frozen=True)
class ApprovalResult:
    ok: bool
    decision_id: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class ExecuteResult:
    ok: bool
    decision_id: str
    status: str
    outcome_id: Optional[str] = None
    execution_id: Optional[str] = None
    message: str = ""


def _next_id(state: WorldState, prefix: str) -> Tuple[WorldState, str]:
    seq = state.seq + 1
    new_state = replace(state, seq=seq)
    return new_state, f"{prefix}-{seq}"


def _stable(value: object) -> str:
    """Deterministic, order-independent string representation used for
    hashing. dict/tuple/frozenset/set are normalized recursively."""
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{_stable(k)}:{_stable(v)}" for k, v in sorted(value.items(), key=lambda kv: _stable(kv[0]))) + "}"
    if isinstance(value, (set, frozenset)):
        return "{" + ",".join(sorted(_stable(v) for v in value)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable(v) for v in value) + "]"
    return json.dumps(value, sort_keys=True, default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def compute_pinned_hash(decision: Decision) -> str:
    """Recompute the content hash over exactly the fields that must remain
    immutable once a decision reaches APPROVED
    (docs/experiment/spec/05_ontology_and_contracts.md, "After APPROVED")."""
    pinned = {
        "decision_type": decision.decision_type,
        "actor_id": decision.actor_id,
        "delegation": decision.delegation,
        "evidence_snapshot_id": decision.evidence_snapshot_id,
        "evidence_hash": decision.evidence_hash,
        "ontology_version": decision.ontology_version,
        "shape_set_version": decision.shape_set_version,
        "authz_model_version": decision.authz_model_version,
        "policy_bundle_version": decision.policy_bundle_version,
        "action_type": decision.action_type,
        "action_version": decision.action_version,
        "params": decision.params,
    }
    return _sha256(pinned)


# ---------------------------------------------------------------------------
# Simple domain transitions
# ---------------------------------------------------------------------------


def add_id_mapping(state: WorldState, source_local_id: str, canonical_id: str) -> Tuple[WorldState, Result]:
    """Record that a source-local identifier resolves to a canonical id
    (docs/experiment/spec/02_scope_and_non_goals.md "Semantic identity
    alignment"). Used by the identity-mapping metamorphic test."""
    new_map = dict(state.id_map)
    new_map[source_local_id] = canonical_id
    new_state = replace(state, id_map=new_map)
    return new_state, Result(ok=True, status="OK", ref=canonical_id)


def resolve_id(state: WorldState, local_or_canonical_id: str) -> str:
    """Resolve a source-local identifier to its canonical id, or pass a
    canonical id through unchanged if there is no mapping for it."""
    return state.id_map.get(local_or_canonical_id, local_or_canonical_id)


def advance_clock(state: WorldState, delta: int = 1) -> Tuple[WorldState, Result]:
    if delta < 0:
        return state, Result(ok=False, status="REJECTED_NEGATIVE_DELTA")
    new_state = replace(state, clock=state.clock + delta)
    return new_state, Result(ok=True, status="OK")


def supplier_delay(
    state: WorldState, po_id: str, new_expected_at: int, reason: str
) -> Tuple[WorldState, Result]:
    po = state.purchase_orders.get(po_id)
    if po is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    if po.status in (PO_RECEIVED, PO_CANCELLED):
        return state, Result(ok=False, status="REJECTED_TERMINAL_PO")
    updated = replace(po, expected_at=new_expected_at, status=PO_DELAYED, delay_reason=reason)
    new_pos = dict(state.purchase_orders)
    new_pos[po_id] = updated
    new_state = replace(state, purchase_orders=new_pos)
    return new_state, Result(ok=True, status="OK", ref=po_id)


def supplier_recovery(
    state: WorldState, po_id: str, expected_at: int
) -> Tuple[WorldState, Result]:
    po = state.purchase_orders.get(po_id)
    if po is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    if po.status in (PO_RECEIVED, PO_CANCELLED):
        return state, Result(ok=False, status="REJECTED_TERMINAL_PO")
    updated = replace(po, expected_at=expected_at, status=PO_OPEN, delay_reason=None)
    new_pos = dict(state.purchase_orders)
    new_pos[po_id] = updated
    new_state = replace(state, purchase_orders=new_pos)
    return new_state, Result(ok=True, status="OK", ref=po_id)


def receive_inventory(
    state: WorldState,
    po_id: str,
    quality_status: str = QUALITY_OK,
) -> Tuple[WorldState, Result]:
    po = state.purchase_orders.get(po_id)
    if po is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    if po.status in (PO_RECEIVED, PO_CANCELLED):
        return state, Result(ok=False, status="REJECTED_TERMINAL_PO")

    key = (po.part, po.destination_warehouse)
    existing = state.inventory.get(key)
    if existing is None:
        new_lot = _fresh_lot(
            lot_id=f"LOT-{po.destination_warehouse}-{po.part}",
            part=po.part,
            warehouse=po.destination_warehouse,
            on_hand=po.qty,
            reserved=0,
            quality_status=quality_status,
            as_of=state.clock,
        )
    else:
        new_lot = replace(existing, on_hand=existing.on_hand + po.qty, as_of=state.clock)

    new_inventory = dict(state.inventory)
    new_inventory[key] = new_lot

    new_pos = dict(state.purchase_orders)
    new_pos[po_id] = replace(po, status=PO_RECEIVED)

    new_state = replace(state, inventory=new_inventory, purchase_orders=new_pos)
    return new_state, Result(ok=True, status="OK", ref=po_id)


def _fresh_lot(lot_id, part, warehouse, on_hand, reserved, quality_status, as_of):
    from reference_model.state import InventoryLot

    return InventoryLot(
        lot_id=lot_id,
        part=part,
        warehouse=warehouse,
        on_hand=on_hand,
        reserved=reserved,
        quality_status=quality_status,
        as_of=as_of,
    )


def reserve_inventory(
    state: WorldState, part: str, warehouse: str, qty: int
) -> Tuple[WorldState, Result]:
    if qty <= 0:
        return state, Result(ok=False, status="REJECTED_NONPOSITIVE_QTY")
    key = (part, warehouse)
    lot = state.inventory.get(key)
    if lot is None or lot.available < qty:
        return state, Result(ok=False, status="REJECTED_INSUFFICIENT_AVAILABLE")
    new_inventory = dict(state.inventory)
    new_inventory[key] = replace(lot, reserved=lot.reserved + qty)
    new_state = replace(state, inventory=new_inventory)
    return new_state, Result(ok=True, status="OK")


def release_inventory(
    state: WorldState, part: str, warehouse: str, qty: int
) -> Tuple[WorldState, Result]:
    if qty <= 0:
        return state, Result(ok=False, status="REJECTED_NONPOSITIVE_QTY")
    key = (part, warehouse)
    lot = state.inventory.get(key)
    if lot is None or lot.reserved < qty:
        return state, Result(ok=False, status="REJECTED_INSUFFICIENT_RESERVED")
    new_inventory = dict(state.inventory)
    new_inventory[key] = replace(lot, reserved=lot.reserved - qty)
    new_state = replace(state, inventory=new_inventory)
    return new_state, Result(ok=True, status="OK")


def reschedule_work_order(
    state: WorldState, work_order_id: str, new_planned_start: int
) -> Tuple[WorldState, Result]:
    wo = state.work_orders.get(work_order_id)
    if wo is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    if wo.status in WORK_ORDER_TERMINAL_STATUSES:
        return state, Result(ok=False, status="REJECTED_TERMINAL_WORK_ORDER")
    new_wos = dict(state.work_orders)
    new_wos[work_order_id] = replace(wo, planned_start=new_planned_start)
    new_state = replace(state, work_orders=new_wos)
    return new_state, Result(ok=True, status="OK", ref=work_order_id)


def cancel_work_order(state: WorldState, work_order_id: str) -> Tuple[WorldState, Result]:
    wo = state.work_orders.get(work_order_id)
    if wo is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    if wo.status in WORK_ORDER_TERMINAL_STATUSES:
        return state, Result(ok=False, status="REJECTED_TERMINAL_WORK_ORDER")
    new_wos = dict(state.work_orders)
    new_wos[work_order_id] = replace(wo, status=WO_CANCELLED)
    new_state = replace(state, work_orders=new_wos)
    return new_state, Result(ok=True, status="OK", ref=work_order_id)


def change_permission(
    state: WorldState,
    actor_id: str,
    role: Optional[str] = None,
    regions: Optional[frozenset] = None,
    task_grants: Optional[frozenset] = None,
) -> Tuple[WorldState, Result]:
    actor = state.actors.get(actor_id)
    if actor is None:
        return state, Result(ok=False, status="REJECTED_NOT_FOUND")
    updated = actor
    if role is not None:
        updated = replace(updated, role=role)
    if regions is not None:
        updated = replace(updated, regions=frozenset(regions))
    if task_grants is not None:
        updated = replace(updated, task_grants=frozenset(task_grants))
    new_actors = dict(state.actors)
    new_actors[actor_id] = updated
    new_state = replace(state, actors=new_actors)
    return new_state, Result(ok=True, status="OK", ref=actor_id)


def change_policy(state: WorldState, new_policy_config: PolicyConfig) -> Tuple[WorldState, Result]:
    new_state = replace(state, policy_config=new_policy_config)
    return new_state, Result(ok=True, status="OK")


# ---------------------------------------------------------------------------
# propose_transfer — the gated decision pipeline
# ---------------------------------------------------------------------------


def _authz_gate(
    state: WorldState, actor_id: str, source_warehouse: str, bugs: Bugs
) -> GateResult:
    if BUG_SKIP_AUTHZ in bugs:
        return GateResult(status=GATE_ALLOW, reason="bug: authz skipped")

    actor = state.actors.get(actor_id)
    if actor is None:
        return GateResult(status=GATE_DENY, reason="unknown actor")

    wh = state.warehouses.get(source_warehouse)
    if wh is None:
        return GateResult(status=GATE_DENY, reason="unknown source warehouse")

    if actor.role == ROLE_JUNIOR_PLANNER:
        # docs/experiment/spec/03_domain_scenario.md: junior_planner "cannot
        # approve high-priority-work-order mitigation". Simplified for this
        # POC (documented ambiguity, see docs/experiment/spec/03) to: a
        # junior_planner can never obtain the can_transfer_inventory
        # authorization, matching the canonical negative case ("Junior user
        # attempts protected transfer" -> authorization = DENY).
        return GateResult(status=GATE_DENY, reason="junior_planner cannot transfer inventory")

    if actor.role in (ROLE_PLANNER, ROLE_SUPERVISOR):
        if wh.region in actor.regions:
            return GateResult(status=GATE_ALLOW)
        return GateResult(status=GATE_DENY, reason="actor outside assigned region")

    if actor.role == ROLE_AGENT:
        if ACTION_TRANSFER_INVENTORY not in actor.task_grants:
            return GateResult(status=GATE_DENY, reason="agent lacks exact task grant")
        if wh.region not in actor.regions:
            return GateResult(status=GATE_DENY, reason="agent outside assigned region")
        return GateResult(status=GATE_ALLOW)

    return GateResult(status=GATE_DENY, reason="unknown role")


def _evidence_gate(
    state: WorldState,
    source_warehouse: str,
    destination_warehouse: str,
    part: str,
) -> Tuple[GateResult, Optional[EvidenceSnapshot]]:
    """Required evidence for transfer_inventory
    (docs/experiment/spec/05_ontology_and_contracts.md ActionType contract
    `evidence_requirements` / `closure`): current_source_inventory,
    destination compatibility, safety_stock, and quality status — all must
    be present and fresh, or the decision is INSUFFICIENT_EVIDENCE. Absence
    is a typed state, never a guessed true/false (H14)."""
    items = {}

    if destination_warehouse not in state.warehouses:
        return GateResult(status=GATE_INSUFFICIENT_EVIDENCE, reason="destination warehouse unknown"), None
    if source_warehouse not in state.warehouses:
        return GateResult(status=GATE_INSUFFICIENT_EVIDENCE, reason="source warehouse unknown"), None

    source_lot = state.inventory.get((part, source_warehouse))
    if source_lot is None:
        return GateResult(status=GATE_INSUFFICIENT_EVIDENCE, reason="missing current_source_inventory"), None

    age = state.clock - source_lot.as_of
    if age > state.policy_config.max_evidence_freshness_s:
        return (
            GateResult(
                status=GATE_INSUFFICIENT_EVIDENCE,
                reason=f"stale source inventory evidence (age={age}s > max={state.policy_config.max_evidence_freshness_s}s)",
            ),
            None,
        )

    safety_stock_key = (part, source_warehouse)
    if safety_stock_key not in state.policy_config.safety_stock:
        return GateResult(status=GATE_INSUFFICIENT_EVIDENCE, reason="missing safety_stock"), None

    items["current_source_inventory"] = EvidenceItem(
        key="current_source_inventory",
        value={"on_hand": source_lot.on_hand, "reserved": source_lot.reserved, "available": source_lot.available},
        origin="WMS",
        observed_at=source_lot.as_of,
        kind="observed",
    )
    items["quality_status"] = EvidenceItem(
        key="quality_status",
        value=source_lot.quality_status,
        origin="WMS",
        observed_at=source_lot.as_of,
        kind="observed",
    )
    items["safety_stock"] = EvidenceItem(
        key="safety_stock",
        value=state.policy_config.safety_stock[safety_stock_key],
        origin="policy_config",
        observed_at=state.clock,
        kind="observed",
    )
    items["current_destination_compatibility"] = EvidenceItem(
        key="current_destination_compatibility",
        value=True,
        origin="WMS",
        observed_at=state.clock,
        kind="derived",
    )

    snapshot_id = f"evidence-{_sha256(items)[:16]}"
    snapshot = EvidenceSnapshot(
        snapshot_id=snapshot_id,
        items=items,
        frozen_at=state.clock,
        content_hash=_sha256(items),
    )
    return GateResult(status=GATE_ALLOW), snapshot


def _policy_gate(
    state: WorldState,
    source_warehouse: str,
    part: str,
    quantity: int,
    bugs: Bugs,
) -> GateResult:
    source_lot = state.inventory[(part, source_warehouse)]

    if source_lot.quality_status == QUALITY_QUARANTINE:
        return GateResult(status=GATE_DENY, reason="source lot is in quarantine")

    safety_stock = state.policy_config.safety_stock[(part, source_warehouse)]
    remaining_after_transfer = source_lot.available - quantity
    if remaining_after_transfer < safety_stock:
        return GateResult(
            status=GATE_DENY,
            reason=(
                f"transfer would breach safety stock "
                f"(remaining={remaining_after_transfer} < safety_stock={safety_stock})"
            ),
        )

    threshold = state.policy_config.transfer_approval_threshold_units
    if BUG_POLICY_THRESHOLD_LT in bugs:
        # Bug: "<=" silently becomes "<" — exactly-at-threshold quantities
        # incorrectly require approval instead of being allowed outright.
        requires_approval = quantity >= threshold
    else:
        requires_approval = quantity > threshold

    if requires_approval:
        return GateResult(
            status=GATE_REQUIRES_APPROVAL,
            reason=f"quantity {quantity} exceeds threshold {threshold}",
        )
    return GateResult(status=GATE_ALLOW)


def _conformance_gate(
    quantity: int,
    source_warehouse: str,
    destination_warehouse: str,
    decision_type: str,
    action_type: str,
    action_version: int,
    ontology_version: str,
    shape_set_version: str,
    authz_model_version: str,
    policy_bundle_version: str,
) -> GateResult:
    """SHACL-shaped structural checks
    (docs/experiment/spec/05_ontology_and_contracts.md "SHACL / conformance")."""
    if quantity < 1:
        return GateResult(status=GATE_INVALID, reason="quantity must be >= 1")
    if source_warehouse == destination_warehouse:
        return GateResult(status=GATE_INVALID, reason="source and destination must differ")
    required_versions = {
        "ontology_version": ontology_version,
        "shape_set_version": shape_set_version,
        "authz_model_version": authz_model_version,
        "policy_bundle_version": policy_bundle_version,
    }
    missing = [k for k, v in required_versions.items() if not v]
    if missing:
        return GateResult(status=GATE_INVALID, reason=f"missing contract version ref(s): {missing}")
    if not decision_type or not action_type:
        return GateResult(status=GATE_INVALID, reason="missing decision_type/action_type")
    return GateResult(status=GATE_ALLOW)


def propose_transfer(
    state: WorldState,
    actor_id: str,
    source_warehouse: str,
    destination_warehouse: str,
    part: str,
    quantity: int,
    work_order_id: Optional[str] = None,
    delegation: Optional[str] = None,
    bugs: Bugs = NO_BUGS,
    contract_versions: Optional[Mapping[str, str]] = None,
    omit_policy_version: bool = False,
) -> Tuple[WorldState, Decision]:
    """Propose a `transfer_inventory` action. Returns (new_state, decision).
    `new_state` differs from `state` only by the newly recorded Decision and
    the incremented id counter — no inventory/work-order mutation happens
    here; those only happen in `execute_transfer`."""
    versions = dict(CONTRACT_VERSIONS_DEFAULT)
    if contract_versions:
        versions.update(contract_versions)
    if omit_policy_version:
        # Test-only hook simulating a decision built with a missing
        # policy-version reference, to exercise the INVALID_CONFORMANCE
        # path described in docs/experiment/spec/03_domain_scenario.md
        # ("SHACL violation ... Decision missing policy-version reference").
        versions["policy_bundle_version"] = ""

    state, decision_id = _next_id(state, "decision")
    params = {
        "source_warehouse": source_warehouse,
        "destination_warehouse": destination_warehouse,
        "part": part,
        "quantity": quantity,
        "work_order_id": work_order_id,
    }

    evidence_gate, snapshot = _evidence_gate(state, source_warehouse, destination_warehouse, part)

    if evidence_gate.status != GATE_ALLOW:
        decision = _build_decision(
            state=state,
            decision_id=decision_id,
            actor_id=actor_id,
            delegation=delegation,
            evidence_snapshot_id="",
            evidence_hash="",
            versions=versions,
            params=params,
            evidence_gate=evidence_gate,
            authz_gate=None,
            policy_gate=None,
            conformance_gate=None,
            status=DECISION_INSUFFICIENT_EVIDENCE,
        )
        return _store_decision(state, decision), decision

    authz_gate = _authz_gate(state, actor_id, source_warehouse, bugs)
    if authz_gate.status != GATE_ALLOW:
        decision = _build_decision(
            state=state,
            decision_id=decision_id,
            actor_id=actor_id,
            delegation=delegation,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_hash=snapshot.content_hash,
            versions=versions,
            params=params,
            evidence_gate=evidence_gate,
            authz_gate=authz_gate,
            policy_gate=None,
            conformance_gate=None,
            status=DECISION_DENIED_AUTHORIZATION,
        )
        return _store_decision(state, decision), decision

    policy_gate = _policy_gate(state, source_warehouse, part, quantity, bugs)
    if policy_gate.status == GATE_DENY:
        decision = _build_decision(
            state=state,
            decision_id=decision_id,
            actor_id=actor_id,
            delegation=delegation,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_hash=snapshot.content_hash,
            versions=versions,
            params=params,
            evidence_gate=evidence_gate,
            authz_gate=authz_gate,
            policy_gate=policy_gate,
            conformance_gate=None,
            status=DECISION_DENIED_POLICY,
        )
        return _store_decision(state, decision), decision
    if policy_gate.status == GATE_REQUIRES_APPROVAL:
        decision = _build_decision(
            state=state,
            decision_id=decision_id,
            actor_id=actor_id,
            delegation=delegation,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_hash=snapshot.content_hash,
            versions=versions,
            params=params,
            evidence_gate=evidence_gate,
            authz_gate=authz_gate,
            policy_gate=policy_gate,
            conformance_gate=None,
            status=DECISION_REQUIRES_APPROVAL,
        )
        return _store_decision(state, decision), decision

    conformance_gate = _conformance_gate(
        quantity=quantity,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        decision_type="shortage_mitigation_transfer",
        action_type=ACTION_TRANSFER_INVENTORY,
        action_version=ACTION_TRANSFER_INVENTORY_VERSION,
        ontology_version=versions["ontology_version"],
        shape_set_version=versions["shape_set_version"],
        authz_model_version=versions["authz_model_version"],
        policy_bundle_version=versions["policy_bundle_version"],
    )
    if conformance_gate.status != GATE_ALLOW:
        decision = _build_decision(
            state=state,
            decision_id=decision_id,
            actor_id=actor_id,
            delegation=delegation,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_hash=snapshot.content_hash,
            versions=versions,
            params=params,
            evidence_gate=evidence_gate,
            authz_gate=authz_gate,
            policy_gate=policy_gate,
            conformance_gate=conformance_gate,
            status=DECISION_INVALID_CONFORMANCE,
        )
        return _store_decision(state, decision), decision

    decision = _build_decision(
        state=state,
        decision_id=decision_id,
        actor_id=actor_id,
        delegation=delegation,
        evidence_snapshot_id=snapshot.snapshot_id,
        evidence_hash=snapshot.content_hash,
        versions=versions,
        params=params,
        evidence_gate=evidence_gate,
        authz_gate=authz_gate,
        policy_gate=policy_gate,
        conformance_gate=conformance_gate,
        status=DECISION_APPROVED,
    )
    return _store_decision(state, decision), decision


def _build_decision(
    state: WorldState,
    decision_id: str,
    actor_id: str,
    delegation: Optional[str],
    evidence_snapshot_id: str,
    evidence_hash: str,
    versions: Mapping[str, str],
    params: Mapping[str, object],
    evidence_gate: Optional[GateResult],
    authz_gate: Optional[GateResult],
    policy_gate: Optional[GateResult],
    conformance_gate: Optional[GateResult],
    status: str,
) -> Decision:
    decision = Decision(
        decision_id=decision_id,
        decision_type="shortage_mitigation_transfer",
        actor_id=actor_id,
        delegation=delegation,
        created_at=state.clock,
        evidence_snapshot_id=evidence_snapshot_id,
        evidence_hash=evidence_hash,
        ontology_version=versions["ontology_version"],
        shape_set_version=versions["shape_set_version"],
        authz_model_version=versions["authz_model_version"],
        policy_bundle_version=versions["policy_bundle_version"],
        action_type=ACTION_TRANSFER_INVENTORY,
        action_version=ACTION_TRANSFER_INVENTORY_VERSION,
        params=params,
        evidence_gate=evidence_gate,
        authz_gate=authz_gate,
        policy_gate=policy_gate,
        conformance_gate=conformance_gate,
        approval=None,
        execution_id=None,
        outcome_id=None,
        status=status,
        content_hash="",
    )
    # content_hash is computed over the pinned fields only, once, at creation.
    return replace(decision, content_hash=compute_pinned_hash(decision))


def _store_decision(state: WorldState, decision: Decision) -> WorldState:
    new_decisions = dict(state.decisions)
    new_decisions[decision.decision_id] = decision
    return replace(state, decisions=new_decisions)


# ---------------------------------------------------------------------------
# approve_decision
# ---------------------------------------------------------------------------


def approve_decision(
    state: WorldState,
    decision_id: str,
    approver_id: str,
    expected_content_hash: str,
) -> Tuple[WorldState, ApprovalResult]:
    decision = state.decisions.get(decision_id)
    if decision is None:
        return state, ApprovalResult(ok=False, decision_id=decision_id, status="REJECTED_NOT_FOUND")

    if decision.status != DECISION_REQUIRES_APPROVAL:
        return state, ApprovalResult(
            ok=False,
            decision_id=decision_id,
            status="REJECTED_WRONG_STATE",
            message=f"decision is {decision.status}, not REQUIRES_APPROVAL",
        )

    approver = state.actors.get(approver_id)
    if approver is None or approver.role != ROLE_SUPERVISOR:
        return state, ApprovalResult(ok=False, decision_id=decision_id, status="REJECTED_NOT_APPROVER")

    # Approval on a decision whose (pinned) content changed since the
    # approver reviewed it is rejected (F33 / H1 "approved decisions
    # immutable").
    if expected_content_hash != decision.content_hash:
        return state, ApprovalResult(
            ok=False,
            decision_id=decision_id,
            status="REJECTED_HASH_MISMATCH",
            message="decision content hash changed since approval was requested",
        )

    approval = Approval(
        approver_id=approver_id,
        approved_at=state.clock,
        decision_content_hash=decision.content_hash,
        policy_bundle_version=decision.policy_bundle_version,
        scope="transfer_inventory",
    )
    updated = replace(decision, status=DECISION_APPROVED, approval=approval)
    assert compute_pinned_hash(updated) == updated.content_hash  # pinned fields unchanged

    new_state = _store_decision(state, updated)
    return new_state, ApprovalResult(ok=True, decision_id=decision_id, status="APPROVED")


# ---------------------------------------------------------------------------
# execute_transfer
# ---------------------------------------------------------------------------


def execute_transfer(
    state: WorldState,
    decision_id: str,
    idempotency_key: str,
    bugs: Bugs = NO_BUGS,
) -> Tuple[WorldState, ExecuteResult]:
    decision = state.decisions.get(decision_id)
    if decision is None:
        return state, ExecuteResult(ok=False, decision_id=decision_id, status="REJECTED_NOT_FOUND")

    # A decision is executable if it is freshly APPROVED, or if it has
    # already gone through execution once (OBSERVED_SUCCESS/DIVERGED/
    # OUTCOME_UNKNOWN/EXECUTION_FAILED) and this call is a *retry* — the
    # idempotency check just below is what makes a retry of an
    # already-completed execution safe
    # (docs/experiment/spec/06_decision_and_action_runtime.md "Exactly-once
    # language": repeated delivery/retry of the same logical ActionExecution
    # must not create duplicate intended business effects). Any decision
    # that never reached APPROVED (REQUIRES_APPROVAL, a denial, DRAFT,
    # PROPOSED) can never be executed.
    executable_statuses = {
        DECISION_APPROVED,
        DECISION_OBSERVED_SUCCESS,
        "DIVERGED",
        "OUTCOME_UNKNOWN",
        "EXECUTION_FAILED",
    }
    if decision.status not in executable_statuses:
        return state, ExecuteResult(
            ok=False,
            decision_id=decision_id,
            status="REJECTED_WRONG_STATE",
            message=f"decision is {decision.status}, was never APPROVED for execution",
        )

    # verify the immutable content hash before acting on it
    if compute_pinned_hash(decision) != decision.content_hash:
        return state, ExecuteResult(ok=False, decision_id=decision_id, status="REJECTED_HASH_MISMATCH")

    # Idempotency: repeated idempotency key => no second effect.
    if idempotency_key in state.applied_idempotency_keys and BUG_SKIP_IDEMPOTENCY not in bugs:
        existing_effect = next(
            (e for e in state.transfer_effects if e.idempotency_key == idempotency_key), None
        )
        existing_outcome = None
        if existing_effect is not None:
            existing_outcome = next(
                (o for o in state.outcomes.values() if o.execution_id == existing_effect.effect_id),
                None,
            )
        return state, ExecuteResult(
            ok=True,
            decision_id=decision_id,
            status="DEDUPED_REPLAY",
            execution_id=existing_effect.effect_id if existing_effect else None,
            outcome_id=existing_outcome.outcome_id if existing_outcome else None,
            message="idempotency key already applied; no new effect created",
        )

    part = decision.params["part"]
    source_warehouse = decision.params["source_warehouse"]
    destination_warehouse = decision.params["destination_warehouse"]
    quantity = decision.params["quantity"]

    # Execution-time re-check (the concurrency race from
    # docs/experiment/spec/09_failure_and_adversarial_matrix.md
    # "Concurrency tests" / docs/experiment/spec/01_hypotheses.md H5): two
    # APPROVED decisions of 80 against 100 available must resolve to exactly
    # one effect, never negative inventory.
    source_lot = state.inventory.get((part, source_warehouse))
    if BUG_SKIP_EXECUTION_RECHECK not in bugs:
        if source_lot is None or source_lot.available < quantity:
            outcome_id, new_state = _record_outcome(
                state,
                decision_id=decision_id,
                execution_id=None,
                status="EXECUTION_FAILED",
                expected={"source_available_decrease": quantity},
                observed={"source_available": source_lot.available if source_lot else 0},
                reason="insufficient stock at execution-time re-check",
                decision_status_override="EXECUTION_FAILED",
            )
            return new_state, ExecuteResult(
                ok=False,
                decision_id=decision_id,
                status="EXECUTION_FAILED",
                outcome_id=outcome_id,
                message="insufficient stock at execution time; needs re-evaluation",
            )

    dest_lot = state.inventory.get((part, destination_warehouse))

    state, effect_id = _next_id(state, "effect")
    effect = ExecutionEffect(
        effect_id=effect_id,
        decision_id=decision_id,
        idempotency_key=idempotency_key,
        part=part,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        quantity=quantity,
        executed_at=state.clock,
    )

    new_inventory = dict(state.inventory)
    new_inventory[(part, source_warehouse)] = replace(
        source_lot, on_hand=source_lot.on_hand - quantity, as_of=state.clock
    )
    if dest_lot is None:
        new_inventory[(part, destination_warehouse)] = _fresh_lot(
            lot_id=f"LOT-{destination_warehouse}-{part}",
            part=part,
            warehouse=destination_warehouse,
            on_hand=quantity,
            reserved=0,
            quality_status=QUALITY_OK,
            as_of=state.clock,
        )
    else:
        new_inventory[(part, destination_warehouse)] = replace(
            dest_lot, on_hand=dest_lot.on_hand + quantity, as_of=state.clock
        )

    new_keys = set(state.applied_idempotency_keys)
    new_keys.add(idempotency_key)

    state = replace(
        state,
        inventory=new_inventory,
        transfer_effects=state.transfer_effects + (effect,),
        applied_idempotency_keys=frozenset(new_keys),
    )

    # Pure-model simplification (docs/adr/0001-lite-mode-for-phase-1.md):
    # execution + CDC-correlated observation are collapsed into one
    # synchronous step. The effect is recorded as expected-and-observed,
    # never a bare command-level "SUCCESS".
    outcome_id, state = _record_outcome(
        state,
        decision_id=decision_id,
        execution_id=effect_id,
        status=DECISION_OBSERVED_SUCCESS,
        expected={
            "source_available_after": source_lot.available - quantity,
            "destination_available_after": (dest_lot.available if dest_lot else 0) + quantity,
        },
        observed={
            "source_available_after": new_inventory[(part, source_warehouse)].available,
            "destination_available_after": new_inventory[(part, destination_warehouse)].available,
        },
        reason="",
        decision_status_override=DECISION_OBSERVED_SUCCESS,
        execution_id_on_decision=effect_id,
    )

    return state, ExecuteResult(
        ok=True,
        decision_id=decision_id,
        status=DECISION_OBSERVED_SUCCESS,
        outcome_id=outcome_id,
        execution_id=effect_id,
    )


def _record_outcome(
    state: WorldState,
    decision_id: str,
    execution_id: Optional[str],
    status: str,
    expected: Mapping[str, object],
    observed: Mapping[str, object],
    reason: str,
    decision_status_override: str,
    execution_id_on_decision: Optional[str] = None,
) -> Tuple[str, WorldState]:
    state, outcome_id = _next_id(state, "outcome")
    outcome = Outcome(
        outcome_id=outcome_id,
        decision_id=decision_id,
        execution_id=execution_id,
        status=status,
        expected=expected,
        observed=observed,
        reason=reason,
    )
    new_outcomes = dict(state.outcomes)
    new_outcomes[outcome_id] = outcome

    decision = state.decisions[decision_id]
    updated_decision = replace(
        decision,
        status=decision_status_override,
        execution_id=execution_id_on_decision if execution_id_on_decision else decision.execution_id,
        outcome_id=outcome_id,
    )
    assert compute_pinned_hash(updated_decision) == updated_decision.content_hash

    new_decisions = dict(state.decisions)
    new_decisions[decision_id] = updated_decision

    new_state = replace(state, outcomes=new_outcomes, decisions=new_decisions)
    return outcome_id, new_state
