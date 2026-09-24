"""W7's seeded incident generator (spec 10: "500-1000 incident sequences").

Deterministic (`random.Random(seed)`) — a controlled MIX across the gate
dimensions that determine a `transfer_inventory` decision's status, not
pure uniform randomness, so a run of N=500 reliably exercises every real
status class (INSUFFICIENT_EVIDENCE / DENIED_AUTHORIZATION / DENIED_POLICY
/ REQUIRES_APPROVAL / APPROVED) rather than mostly landing on one.

Each scenario gets its OWN synthetic part index (tests/ab/synthetic.py's
reserved 7000+ range, offset by `INDEX_OFFSET` so W7 never collides with
W1-W6's indices 1-6) — fully independent inventory state per scenario, so
all N can be seeded once and proposed in any order with no cross-scenario
interference.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

INDEX_OFFSET = 1000  # W7 uses part_ids(INDEX_OFFSET + i) for i in range(n)

AUTHORIZED_WAREHOUSES = ("WH-A", "WH-B")
UNAUTHORIZED_WAREHOUSES = ("WH-C", "WH-D")
# contracts/authorization/v1/model.fga: can_transfer_inventory = planner OR
# junior_planner OR agent_grant — `supervisor` is NOT unioned into it
# (supervisor only holds can_approve_large_transfer/can_mitigate_high_priority
# — an APPROVER role, never a PROPOSER). Only planner-1 is used as the
# "authorized proposer" actor: reference_model.transitions._authz_gate (the
# W7 oracle, tests/ab/oracle.py) is Phase 1 code with its OWN documented
# simplification here ("junior_planner cannot transfer inventory" — real
# model allows it; supervisor treated as equivalent to planner — real model
# excludes it from can_transfer_inventory) that predates OpenFGA and was
# never meant to referee role-level authorization precisely. Using
# planner-1 exclusively for "should succeed" scenarios keeps the oracle
# comparison sound; junior-1's REAL (correct) authorization behavior is
# still exercised for INTER-VARIANT comparison (`role_denied` bucket,
# oracle comparison skipped for it explicitly — see generate() below).
ACTORS_AUTHORIZED = ("planner-1",)
ACTORS_UNAUTHORIZED = ("junior-1",)


@dataclass(frozen=True)
class Scenario:
    seq: int
    index: int  # -> synthetic.part_ids(index)
    seed_inventory: bool
    source_warehouse: str
    destination_warehouse: str
    on_hand: int
    quantity: int
    quality_status: str
    actor_id: str
    expected_class: str  # a coarse LABEL this generator intends (not authoritative — the real gates decide)
    skip_oracle: bool = False  # True for scenarios the Phase 1 oracle is KNOWN to model differently from the real OpenFGA authz (see ACTORS_AUTHORIZED's comment) — inter-variant comparison still applies


def generate(n: int, seed: int) -> list[Scenario]:
    rng = random.Random(seed)
    scenarios: list[Scenario] = []
    for i in range(n):
        index = INDEX_OFFSET + i
        bucket = rng.choices(
            ["insufficient_evidence", "denied_authorization_role", "denied_authorization_region", "denied_policy_safety_stock", "denied_policy_quarantine", "requires_approval", "approved"],
            weights=[10, 12, 12, 15, 8, 20, 23],
            k=1,
        )[0]

        if bucket == "insufficient_evidence":
            # source != "WH-A" guaranteed (WH-B fixed) — a same-warehouse
            # transfer is rejected as MalformedProposal (HTTP 422) before
            # evidence gathering ever runs, which is a DIFFERENT F01 case
            # this bucket isn't testing.
            scenarios.append(Scenario(i, index, False, "WH-B", "WH-A", 0, rng.randint(1, 20), "OK", rng.choice(ACTORS_AUTHORIZED), bucket))
            continue

        source = rng.choice(AUTHORIZED_WAREHOUSES)
        dest = "WH-A" if source != "WH-A" else "WH-B"

        if bucket == "denied_authorization_role":
            scenarios.append(Scenario(i, index, True, source, dest, rng.randint(50, 200), rng.randint(1, 20), "OK", rng.choice(ACTORS_UNAUTHORIZED), bucket, skip_oracle=True))
            continue
        if bucket == "denied_authorization_region":
            unauth_source = rng.choice(UNAUTHORIZED_WAREHOUSES)
            scenarios.append(Scenario(i, index, True, unauth_source, dest, rng.randint(50, 200), rng.randint(1, 20), "OK", rng.choice(ACTORS_AUTHORIZED), bucket))
            continue
        if bucket == "denied_policy_safety_stock":
            # on_hand chosen so remaining-after-transfer < safety_stock(15).
            qty = rng.randint(10, 30)
            on_hand = qty + rng.randint(0, 10)  # remaining <= 10 < 15
            scenarios.append(Scenario(i, index, True, source, dest, on_hand, qty, "OK", rng.choice(ACTORS_AUTHORIZED), bucket))
            continue
        if bucket == "denied_policy_quarantine":
            scenarios.append(Scenario(i, index, True, source, dest, rng.randint(50, 200), rng.randint(1, 20), "QUARANTINE", rng.choice(ACTORS_AUTHORIZED), bucket))
            continue
        if bucket == "requires_approval":
            qty = rng.randint(81, 150)
            on_hand = qty + rng.randint(20, 100)
            scenarios.append(Scenario(i, index, True, source, dest, on_hand, qty, "OK", rng.choice(ACTORS_AUTHORIZED), bucket))
            continue
        # approved
        qty = rng.randint(1, 79)
        on_hand = qty + rng.randint(16, 150)
        scenarios.append(Scenario(i, index, True, source, dest, on_hand, qty, "OK", rng.choice(ACTORS_AUTHORIZED), bucket))

    return scenarios
