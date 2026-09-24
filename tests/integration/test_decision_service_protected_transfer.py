"""Phase 6 step 0 (docs/adr/0003-protected-high-priority-transfer-authorization.md):
the spec 03 canonical negative case — "Unauthorized actor: junior user
attempts protected transfer -> authorization = DENY, external_effects = 0"
— proved end to end against the real HTTP API.

Uses a REAL, currently at-risk, HIGH-priority work order discovered live
from the hot projection (preferring WO-42, falling back to any other seeded
one) rather than a hard-coded fixture id: `tests/integration/test_canonical_scenario.py`
(Phase 2) permanently mitigates WO-42 the first time the full suite drives
it, so a test hard-coded to WO-42 would pass in isolation but could fail (or
skip for the wrong reason) depending on `make test`'s file collection order
— see decision_helpers.py's own module docstring for the same concern about
WO-42/PX-17.

Zero-external-effects is trivially true for every propose()-only test below
(as it is for every other pre-Phase-6-execute decision-service test): this
phase's `POST /decisions/{id}/execute` still returns 501 through step 0 — no
code path from `propose()` ever calls WMS. The real "0 effects" proof for a
protected DENY, once execution exists, is identical to F03/F04's existing
`inventory_unchanged` proof.
"""

from __future__ import annotations

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from tests.integration.decision_helpers import set_inventory_and_wait


def _find_high_priority_route(conn: psycopg.Connection) -> dict | None:
    """A real (part, source_warehouse, destination_warehouse) triple that IS
    a transfer_candidates row for a currently HIGH-priority, at-risk work
    order — the candidate with the most headroom over `default_safety_stock`
    (10, contracts/policies/v1/data.json) so a 1-unit test transfer can
    never itself be denied by the safety-stock policy gate, which would
    confound the authorization-only assertions this file makes.

    Phase 10a step 0 regression-verification fix: this used to prefer WO-42
    (`ORDER BY (tc.work_order_id = 'WO-42') DESC, ...`) — the EXACT same
    anti-pattern implementation-notes.md's Phase 9 section already found
    and fixed in a SIBLING file
    (tests/integration/test_forensic_queries_phase6.py::_find_at_risk_route),
    just never noticed here. WO-42 is the canonical, shared, EVERYONE-
    touches-it fixture (common.md: "Never mutate the canonical fixture...
    except in tests that explicitly restore it") — picking it introduces a
    TOCTOU window between this SELECT and the caller's later `propose()`
    call in a long-lived, heavily multi-agent-tested stack: another
    process's concurrent mitigation of WO-42 between the two can flip this
    test's outcome from APPROVED to DENIED_POLICY, reproduced live during
    this phase's own regression-confirmation run. Excluding WO-42 entirely
    (rather than merely deprioritizing it) is the same remedy Phase 9's fix
    used, for the same reason: deprioritizing alone does not help when it
    is the only row that still qualifies once a headroom-losing test has
    run against everything else."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT tc.* FROM transfer_candidates tc
            JOIN work_order_risk wor ON wor.work_order_id = tc.work_order_id
            WHERE wor.priority = 'HIGH' AND wor.at_risk = true
              AND tc.work_order_id != 'WO-42'
              -- Scoped to WH-A/WH-B: the only warehouses
              -- contracts/authorization/v1/tuples.yaml grants ANY canonical
              -- actor (junior-1/planner-1/supervisor-1) authority over —
              -- every other seeded warehouse denies EVERYONE at the base
              -- can_transfer_inventory check, which would confound this
              -- file's authorization-only assertions.
              AND tc.source_warehouse IN ('WH-A', 'WH-B')
            ORDER BY tc.available_at_source DESC
            LIMIT 10
            """
        )
        rows = cur.fetchall()
    for row in rows:
        if row["available_at_source"] >= 11:  # remaining after qty=1 >= default_safety_stock (10)
            return row
    return None


@pytest.fixture()
def high_priority_route(ontology_hot_conn: psycopg.Connection) -> dict:
    row = _find_high_priority_route(ontology_hot_conn)
    if row is None:
        pytest.skip(
            "no currently HIGH-priority, at-risk work order with a transfer_candidates "
            "route (and >= 11 available at source) exists in the seeded dataset right now "
            "— run against a freshly seeded stack, or before another test fully mitigates it"
        )
    return row


def _propose(decision_client: httpx.Client, actor_id: str, route: dict, declare_work_order: bool) -> httpx.Response:
    parameters = {
        "source_warehouse": route["source_warehouse"],
        "destination_warehouse": route["destination_warehouse"],
        "part": route["part"],
        "quantity": 1,
    }
    if declare_work_order:
        parameters["work_order"] = route["work_order_id"]
    return decision_client.post(
        "/decisions/propose",
        json={"action_type": "transfer_inventory", "actor": {"type": "user", "id": actor_id}, "parameters": parameters, "context": {}},
    )


def test_junior_declaring_the_high_priority_work_order_is_denied(decision_client: httpx.Client, high_priority_route: dict):
    r = _propose(decision_client, "junior-1", high_priority_route, declare_work_order=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DENIED_AUTHORIZATION", body
    assert body["authorization_result"]["outcome"] == "DENIED"
    assert body["authorization_result"]["relation"] == "can_mitigate_high_priority"
    assert body["evidence_snapshot"]["facts_used"]["route_protection"]["status"] == "PROTECTED"
    assert high_priority_route["work_order_id"] in body["evidence_snapshot"]["facts_used"]["route_protection"]["work_order_ids"]


def test_junior_omitting_work_order_is_still_denied_security_fix(decision_client: httpx.Client, high_priority_route: dict):
    """Security review fix: a junior cannot avoid the protected check merely
    by not declaring `work_order` — the server derives protection from the
    proposed route itself, never from caller-declared context."""
    r = _propose(decision_client, "junior-1", high_priority_route, declare_work_order=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DENIED_AUTHORIZATION", body
    assert body["evidence_snapshot"]["facts_used"]["route_protection"]["status"] == "PROTECTED"


def test_planner_declaring_the_high_priority_work_order_is_allowed(decision_client: httpx.Client, high_priority_route: dict):
    r = _propose(decision_client, "planner-1", high_priority_route, declare_work_order=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED", body
    assert body["authorization_result"]["outcome"] == "ALLOWED"


def test_junior_transfer_unrelated_to_any_high_priority_work_order_is_still_allowed(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    """Unchanged from Phase 5: a synthetic part with no transfer_candidates
    row at all is NOT_APPLICABLE for route protection, so junior-1 proceeds
    exactly as before this ADR."""
    source_sku = "SKU-900701"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "junior-1"},
            "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
            "context": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED", body
    assert body["evidence_snapshot"]["facts_used"]["route_protection"]["status"] == "NOT_APPLICABLE"


def test_unresolvable_priority_fails_closed_for_every_actor(
    decision_client: httpx.Client, ontology_hot_conn: psycopg.Connection, high_priority_route: dict
):
    """Security review fix: if the route matches an at-risk work order but
    its priority/at-risk state cannot be verified FRESH, the proposal is
    INSUFFICIENT_EVIDENCE for EVERY actor — including planner-1, who would
    otherwise sail through the protected check. 'Cannot determine' must mean
    'deny', never 'allow'."""
    wo_id = high_priority_route["work_order_id"]
    with ontology_hot_conn.cursor() as cur:
        cur.execute("UPDATE work_order_risk SET computed_at = now() - interval '30 seconds' WHERE work_order_id = %s", (wo_id,))
    try:
        r = _propose(decision_client, "planner-1", high_priority_route, declare_work_order=False)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "INSUFFICIENT_EVIDENCE", body
        assert "route_protection_fresh" in body["evidence_snapshot"]["missing"]
    finally:
        # Best-effort — the live projection_builder poll cycle overwrites
        # this regardless within OO_PROJECTION_POLL_INTERVAL_S (default 3s).
        with ontology_hot_conn.cursor() as cur:
            cur.execute("UPDATE work_order_risk SET computed_at = now() WHERE work_order_id = %s", (wo_id,))


def test_declaring_a_mismatched_at_risk_work_order_is_insufficient_evidence(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, high_priority_route: dict
):
    """Honesty check (security review): declaring a REAL, at-risk work order
    that the proposed route does NOT actually mitigate is rejected, rather
    than silently accepted as an unrelated/harmless label."""
    source_sku = "SKU-900702"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {
                "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30,
                "work_order": high_priority_route["work_order_id"],
            },
            "context": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "INSUFFICIENT_EVIDENCE", body
    assert "work_order_route_mismatch" in body["evidence_snapshot"]["missing"]
