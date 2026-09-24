"""The reference-model oracle for `transfer_inventory` (spec 10's
"correctness: decision match vs reference_model"; spec 08's "Level 0: a
small deterministic Python model acts as oracle").

Reuses `reference_model.transitions.propose_transfer` UNCHANGED — the
Phase 1 pure-Python pipeline (evidence -> authz -> policy -> conformance
gates over an in-memory `WorldState`) that both live variants' real
propose() flows were originally validated against. This module's only job
is building a `WorldState` that reflects the SAME V2/V3-era contract
values currently deployed live (`contracts/manifests/deployed_version.json`:
policies=v2, actions=v3) so the oracle's verdict is comparable to what the
live stack SHOULD produce, not a stale V1 comparison:

  - `transfer_approval_threshold_units = 80` (contracts/actions/v2|v3/
    transfer_inventory.yaml's `policy.approval_threshold_units`).
  - `safety_stock = 15` (contracts/policies/v2/data.json's
    `default_safety_stock_v2` — synthetic parts never have a per-part
    override).
  - `max_evidence_freshness_s = 5`.

Known gap, scoped deliberately (see docs/experiment/implementation-notes.md
Phase 8 item 2): the reference model's `_policy_gate` has no
`reservation_ok`/on_hand-vs-reserved hard-deny rule (V2's ONLY policy
addition over V1 — contracts/policies/v2/transfer_inventory.rego). Every
oracle-compared scenario in this module therefore uses `reserved=0`, which
makes V2's `remaining = on_hand - reserved - quantity` formula and the
reference model's `available - quantity` formula IDENTICAL, and makes
`reservation_ok` trivially True either way — so this gap contributes zero
divergence for THESE scenarios specifically, by construction, not by luck.
A `reserved > 0` scenario is a real, disclosed gap this oracle cannot
referee; W7's broader corpus (tests/ab/test_w7_generated_corpus.py) compares
the two LIVE variants against each other instead, which needs no oracle.

Actor/region facts below are the REAL, live `contracts/authorization/v1/model.fga`
tuple population (read directly off a live `authz.check()` tuple snapshot
during Phase 8 development — see the docstring on `KNOWN_REGION_WAREHOUSES`),
not guessed: `planner-1`/`supervisor-1` are granted via `region-1`, which
covers ONLY `WH-A`/`WH-B`; `junior-1` is directly denied
(`can_transfer_inventory` requires `planner`/`supervisor`, `junior_planner`
never satisfies it); any warehouse with no authorizing region tuple (e.g.
`WH-C`, `WH-D`) denies EVERY actor for a source-bound relation.
"""

from __future__ import annotations

from reference_model.state import (
    ROLE_JUNIOR_PLANNER,
    ROLE_PLANNER,
    ROLE_SUPERVISOR,
    Actor,
    InventoryLot,
    PolicyConfig,
    Warehouse,
    WorkOrder,
    empty_state,
)
from reference_model.transitions import propose_transfer

# Real, deployed contract values (see module docstring) — kept here rather
# than re-derived from contracts/ on every call, since this is comparing
# against a SPECIFIC known-live deployment already verified during Phase 8
# build (docs/experiment/implementation-notes.md); a real redeploy would
# need this updated alongside it, same as any other pinned expectation.
V2_APPROVAL_THRESHOLD_UNITS = 80
V2_DEFAULT_SAFETY_STOCK = 15
MAX_EVIDENCE_FRESHNESS_S = 5

# WH-A/WH-B are granted to planner-1/supervisor-1 via region-1; WH-C/WH-D
# carry no authorizing region tuple in the live store at all.
AUTHORIZED_WAREHOUSES = frozenset({"WH-A", "WH-B"})
UNAUTHORIZED_WAREHOUSES = frozenset({"WH-C", "WH-D"})


def build_actors() -> dict[str, Actor]:
    return {
        "planner-1": Actor(actor_id="planner-1", role=ROLE_PLANNER, regions=frozenset({"region-1"})),
        "supervisor-1": Actor(actor_id="supervisor-1", role=ROLE_SUPERVISOR, regions=frozenset({"region-1"})),
        "junior-1": Actor(actor_id="junior-1", role=ROLE_JUNIOR_PLANNER, regions=frozenset({"region-1"})),
    }


def build_warehouses() -> dict[str, Warehouse]:
    # The reference model's `_authz_gate` checks `wh.region in actor.regions`
    # — model region-1 for WH-A/WH-B (the actually-authorized pair) and a
    # DISTINCT, nobody-holds-it region for WH-C/WH-D, mirroring the real
    # store's "no authorizing tuple at all" shape (not "authorized for a
    # different region", which would exercise a different real code path).
    return {
        "WH-A": Warehouse(warehouse_id="WH-A", region="region-1"),
        "WH-B": Warehouse(warehouse_id="WH-B", region="region-1"),
        "WH-C": Warehouse(warehouse_id="WH-C", region="region-unheld"),
        "WH-D": Warehouse(warehouse_id="WH-D", region="region-unheld"),
    }


def build_state(
    part: str,
    source_warehouse: str,
    destination_warehouse: str,
    source_on_hand: int,
    destination_on_hand: int = 0,
    source_quality: str = "OK",
    clock: int = 0,
    source_as_of: int | None = None,
):
    warehouses = build_warehouses()
    actors = build_actors()
    policy_config = PolicyConfig(
        transfer_approval_threshold_units=V2_APPROVAL_THRESHOLD_UNITS,
        safety_stock={(part, source_warehouse): V2_DEFAULT_SAFETY_STOCK},
        max_evidence_freshness_s=MAX_EVIDENCE_FRESHNESS_S,
    )
    state = empty_state(warehouses=warehouses, actors=actors, policy_config=policy_config, clock=clock)
    lots = dict(state.inventory)
    lots[(part, source_warehouse)] = InventoryLot(
        lot_id=f"oracle-lot-{part}-{source_warehouse}", part=part, warehouse=source_warehouse,
        on_hand=source_on_hand, reserved=0, quality_status=source_quality,
        as_of=clock if source_as_of is None else source_as_of,
    )
    if destination_warehouse in warehouses:
        lots[(part, destination_warehouse)] = InventoryLot(
            lot_id=f"oracle-lot-{part}-{destination_warehouse}", part=part, warehouse=destination_warehouse,
            on_hand=destination_on_hand, reserved=0, quality_status="OK", as_of=clock,
        )
    return state.__class__(**{**state.__dict__, "inventory": lots})


def expected_transfer_status(
    part: str, source_warehouse: str, destination_warehouse: str, quantity: int,
    actor_id: str, source_on_hand: int, destination_on_hand: int = 0,
    source_quality: str = "OK",
) -> tuple[str, str]:
    """Returns (status, reason) — the SAME status vocabulary both live
    variants use (INSUFFICIENT_EVIDENCE/DENIED_AUTHORIZATION/DENIED_POLICY/
    REQUIRES_APPROVAL/APPROVED)."""
    state = build_state(part, source_warehouse, destination_warehouse, source_on_hand, destination_on_hand, source_quality)
    _new_state, decision = propose_transfer(
        state, actor_id=actor_id, source_warehouse=source_warehouse, destination_warehouse=destination_warehouse,
        part=part, quantity=quantity,
    )
    reason = ""
    for gate in (decision.evidence_gate, decision.authz_gate, decision.policy_gate, decision.conformance_gate):
        if gate is not None and gate.reason:
            reason = gate.reason
    return decision.status, reason
