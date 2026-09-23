"""Pure domain state for the operational-ontology POC reference model.

This module has NO dependency on network, database, RDF, or an LLM — it is
Level 0 of docs/experiment/spec/08_test_strategy.md ("A small deterministic
Python model acts as oracle"). All types are frozen dataclasses; nothing in
this package mutates a `WorldState` in place. Every transition in
`transitions.py` returns a brand-new `WorldState`.

Time unit: an integer "tick" (interpreted as hours in the canonical incident
fixture, see seed/fixtures/canonical_incident.yaml). `WorldState.clock` is a
logical clock, never wall-clock time — this keeps the model deterministic and
matches docs/experiment/spec/09_failure_and_adversarial_matrix.md F35
("ordering relies on source offsets/IDs where required, not wall clock
alone").

Decision lifecycle statuses are exactly the names from
docs/experiment/spec/05_ontology_and_contracts.md. No bare "SUCCESS" status
exists anywhere in this model — success is always qualified as
OBSERVED_SUCCESS (or, in later phases, distinguished from command-level
acceptance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Enumerated constants (kept as plain strings rather than enum.Enum so they
# serialize trivially into hashes/snapshots and match spec vocabulary
# verbatim).
# ---------------------------------------------------------------------------

WO_PLANNED = "PLANNED"
WO_RELEASED = "RELEASED"
WO_RUNNING = "RUNNING"
WO_DONE = "DONE"
WO_CANCELLED = "CANCELLED"
WORK_ORDER_STATUSES = frozenset({WO_PLANNED, WO_RELEASED, WO_RUNNING, WO_DONE, WO_CANCELLED})
WORK_ORDER_TERMINAL_STATUSES = frozenset({WO_DONE, WO_CANCELLED})
WORK_ORDER_OPEN_STATUSES = WORK_ORDER_STATUSES - WORK_ORDER_TERMINAL_STATUSES

QUALITY_OK = "OK"
QUALITY_QUARANTINE = "QUARANTINE"
QUALITY_STATUSES = frozenset({QUALITY_OK, QUALITY_QUARANTINE})

PO_OPEN = "OPEN"
PO_DELAYED = "DELAYED"
PO_RECEIVED = "RECEIVED"
PO_CANCELLED = "CANCELLED"
PO_STATUSES = frozenset({PO_OPEN, PO_DELAYED, PO_RECEIVED, PO_CANCELLED})

ROLE_PLANNER = "planner"
ROLE_JUNIOR_PLANNER = "junior_planner"
ROLE_SUPERVISOR = "supervisor"
ROLE_AGENT = "agent"
ROLES = frozenset({ROLE_PLANNER, ROLE_JUNIOR_PLANNER, ROLE_SUPERVISOR, ROLE_AGENT})

# Decision lifecycle — docs/experiment/spec/05_ontology_and_contracts.md
DECISION_DRAFT = "DRAFT"
DECISION_PROPOSED = "PROPOSED"
DECISION_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
DECISION_DENIED_AUTHORIZATION = "DENIED_AUTHORIZATION"
DECISION_DENIED_POLICY = "DENIED_POLICY"
DECISION_INVALID_CONFORMANCE = "INVALID_CONFORMANCE"
DECISION_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
DECISION_APPROVED = "APPROVED"
DECISION_EXECUTING = "EXECUTING"
DECISION_EXECUTION_FAILED = "EXECUTION_FAILED"
DECISION_OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
DECISION_AWAITING_OBSERVATION = "AWAITING_OBSERVATION"
DECISION_DIVERGED = "DIVERGED"
DECISION_OBSERVED_SUCCESS = "OBSERVED_SUCCESS"

DECISION_TERMINAL_DENIALS = frozenset(
    {
        DECISION_INSUFFICIENT_EVIDENCE,
        DECISION_DENIED_AUTHORIZATION,
        DECISION_DENIED_POLICY,
        DECISION_INVALID_CONFORMANCE,
    }
)
# Statuses that must never carry an execution_id (proof of zero external effects).
DECISION_NO_EFFECT_STATUSES = DECISION_TERMINAL_DENIALS | {
    DECISION_DRAFT,
    DECISION_PROPOSED,
    DECISION_REQUIRES_APPROVAL,
}

# Fields pinned/immutable once a decision reaches APPROVED
# (docs/experiment/spec/05_ontology_and_contracts.md, "After APPROVED").
# content_hash is computed over exactly these fields.
PINNED_DECISION_FIELDS = (
    "decision_type",
    "actor_id",
    "delegation",
    "evidence_snapshot_id",
    "evidence_hash",
    "ontology_version",
    "shape_set_version",
    "authz_model_version",
    "policy_bundle_version",
    "action_type",
    "action_version",
    "params",
)

# ---------------------------------------------------------------------------
# Bug injection flags (for the Phase 1 mutation/bug-detection exit criterion).
# Never read from the environment in production code paths — always passed
# explicitly by the caller (tests only).
# ---------------------------------------------------------------------------

BUG_POLICY_THRESHOLD_LT = "POLICY_THRESHOLD_LT"
BUG_SKIP_IDEMPOTENCY = "SKIP_IDEMPOTENCY"
BUG_SKIP_EXECUTION_RECHECK = "SKIP_EXECUTION_RECHECK"
BUG_SKIP_AUTHZ = "SKIP_AUTHZ"

ALL_BUGS = frozenset(
    {
        BUG_POLICY_THRESHOLD_LT,
        BUG_SKIP_IDEMPOTENCY,
        BUG_SKIP_EXECUTION_RECHECK,
        BUG_SKIP_AUTHZ,
    }
)

Bugs = FrozenSet[str]
NO_BUGS: Bugs = frozenset()

# Gate result vocabulary (shared by transitions.py and invariants.py).
GATE_ALLOW = "ALLOW"
GATE_DENY = "DENY"
GATE_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
GATE_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
GATE_INVALID = "INVALID"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Warehouse:
    warehouse_id: str
    region: str


@dataclass(frozen=True)
class InventoryLot:
    lot_id: str
    part: str
    warehouse: str
    on_hand: int
    reserved: int
    quality_status: str
    as_of: int  # logical clock tick at which this fact was last observed

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass(frozen=True)
class WorkOrder:
    work_order_id: str
    status: str
    priority: str
    planned_start: int
    warehouse: str
    requirements: Mapping[str, int]  # part -> qty


@dataclass(frozen=True)
class PurchaseOrder:
    po_id: str
    part: str
    qty: int
    destination_warehouse: str
    expected_at: int
    status: str = PO_OPEN
    delay_reason: Optional[str] = None


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    regions: FrozenSet[str]
    task_grants: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class PolicyConfig:
    transfer_approval_threshold_units: int = 100
    # keyed by (part, warehouse) -> minimum on_hand that must remain as source
    safety_stock: Mapping[Tuple[str, str], int] = field(default_factory=dict)
    max_evidence_freshness_s: int = 5


@dataclass(frozen=True)
class EvidenceItem:
    key: str
    value: object
    origin: str
    observed_at: int
    kind: str = "observed"  # observed | inferred | derived | human_assertion | agent_assertion


@dataclass(frozen=True)
class EvidenceSnapshot:
    snapshot_id: str
    items: Mapping[str, EvidenceItem]
    frozen_at: int
    content_hash: str


@dataclass(frozen=True)
class GateResult:
    status: str
    reason: str = ""
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Approval:
    approver_id: str
    approved_at: int
    decision_content_hash: str
    policy_bundle_version: str
    scope: str


@dataclass(frozen=True)
class ExecutionEffect:
    """A durable record of an applied external effect (models the WMS side
    effect + its correlated CDC observation, collapsed synchronously per
    docs/adr/0001-lite-mode-for-phase-1.md)."""

    effect_id: str
    decision_id: str
    idempotency_key: str
    part: str
    source_warehouse: str
    destination_warehouse: str
    quantity: int
    executed_at: int


@dataclass(frozen=True)
class Outcome:
    outcome_id: str
    decision_id: str
    execution_id: Optional[str]
    status: str  # OBSERVED_SUCCESS | DIVERGED | OUTCOME_UNKNOWN | EXECUTION_FAILED
    expected: Mapping[str, object]
    observed: Mapping[str, object]
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    decision_id: str
    decision_type: str
    actor_id: str
    delegation: Optional[str]  # human actor_id if actor_id is an agent acting under delegation
    created_at: int

    evidence_snapshot_id: str
    evidence_hash: str

    ontology_version: str
    shape_set_version: str
    authz_model_version: str
    policy_bundle_version: str

    action_type: str
    action_version: int
    params: Mapping[str, object]

    evidence_gate: Optional[GateResult]
    authz_gate: Optional[GateResult]
    policy_gate: Optional[GateResult]
    conformance_gate: Optional[GateResult]

    approval: Optional[Approval]
    execution_id: Optional[str]
    outcome_id: Optional[str]

    status: str
    content_hash: str  # sha256 over PINNED_DECISION_FIELDS only


@dataclass(frozen=True)
class WorldState:
    clock: int
    seq: int  # monotonic counter used to mint deterministic, collision-free ids

    inventory: Mapping[Tuple[str, str], InventoryLot]  # (part, warehouse) -> lot
    work_orders: Mapping[str, WorkOrder]
    purchase_orders: Mapping[str, PurchaseOrder]
    warehouses: Mapping[str, Warehouse]
    actors: Mapping[str, Actor]

    policy_config: PolicyConfig

    decisions: Mapping[str, Decision]
    applied_idempotency_keys: FrozenSet[str]
    transfer_effects: Tuple[ExecutionEffect, ...]
    outcomes: Mapping[str, Outcome]

    # source-local-id -> canonical-id, for the identity-mapping metamorphic
    # test (docs/experiment/spec/08_test_strategy.md "Metamorphic tests").
    id_map: Mapping[str, str] = field(default_factory=dict)


def empty_state(
    warehouses: Mapping[str, Warehouse],
    actors: Mapping[str, Actor],
    policy_config: PolicyConfig,
    clock: int = 0,
) -> WorldState:
    return WorldState(
        clock=clock,
        seq=0,
        inventory={},
        work_orders={},
        purchase_orders={},
        warehouses=dict(warehouses),
        actors=dict(actors),
        policy_config=policy_config,
        decisions={},
        applied_idempotency_keys=frozenset(),
        transfer_effects=tuple(),
        outcomes={},
        id_map={},
    )
