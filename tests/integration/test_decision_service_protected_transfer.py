"""Phase 6 step 0 (docs/adr/0003-protected-high-priority-transfer-authorization.md):
the spec 03 canonical negative case — "Unauthorized actor: junior user
attempts protected transfer -> authorization = DENY, external_effects = 0"
— proved end to end against the real HTTP API.

Phase 10 fix (docs/experiment/briefs/phase10fix.md "self-contained
fixtures"): `high_priority_route` below builds its OWN synthetic
HIGH-priority, at-risk work order and transfer_candidates route (via
`tests/integration/decision_helpers.py::create_at_risk_work_order_and_wait`)
rather than discovering a REAL one live from the hot projection. Scavenging
a real seeded route used to fail non-deterministically for two REAL,
unrelated reasons the orchestrator reproduced on a quiet host: (1) the
scavenged route's destination lot could land on one of
`seed/generators/generate.py`'s own 5%-weighted QUARANTINE draws — a
genuine property of the SEED=42 dataset, not test leftover — denying the
proposal for a reason this file has nothing to do with; (2) a different,
already-run test could have mitigated the scavenged work order below the
HIGH-priority-candidate threshold between the SELECT and this file's later
`propose()` call (the same TOCTOU class the Phase 9/10a fixes already
patched for WO-42 specifically, just not for every other seeded work order
scavenging can land on). A synthetic, per-fixture-call work order/route is
immune to both: it is never touched by any other test, and its destination
lot is a synthetic part/warehouse pair this fixture ALWAYS sets to
`quality_status="OK"` itself (never a real seeded lot subject to the
generator's own random QUARANTINE draw).

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

from tests.integration.decision_helpers import create_at_risk_work_order_and_wait, set_inventory_and_wait

# Reserved synthetic index (see decision_helpers.py's own reserved-range
# comment) and a fixed, clearly-synthetic work_order_id — reused across
# every fixture invocation in this file (one per test that requests
# `high_priority_route`). Each invocation fully REPLACES the work order's
# priority/requirements and the source lot's on_hand
# (create_at_risk_work_order_and_wait is idempotent), so reuse never
# depends on — or leaks into — another test's state.
_WORK_ORDER_ID = "WO-TEST-PROTECTED-01"
_PART_INDEX = 1001


@pytest.fixture()
def high_priority_route(
    mes_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
) -> dict:
    return create_at_risk_work_order_and_wait(
        mes_client,
        wms_client,
        ontology_hot_conn,
        _WORK_ORDER_ID,
        index=_PART_INDEX,
        priority="HIGH",
        source_warehouse="WH-B",
        destination_warehouse="WH-A",
        shortfall=20,
        source_on_hand=100,  # >> default_safety_stock (10) + this file's 1-unit test transfers
    )


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
