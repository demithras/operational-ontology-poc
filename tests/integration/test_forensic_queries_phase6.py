"""H13 queries 6-8 (Phase 6: "which external objects changed", "what outcome
was actually observed", "which later decisions depended on that outcome")
plus spec 03's own acceptance line: "After OBSERVED_SUCCESS, the canonical
incident's work_order_risk projection changes from critical to mitigated".

Phase 10 fix (docs/experiment/briefs/phase10fix.md "self-contained
fixtures"): `at_risk_route` below builds its OWN synthetic at-risk work
order and transfer_candidates route (via
`tests/integration/decision_helpers.py::create_at_risk_work_order_and_wait`)
rather than discovering a REAL one live from the hot projection — same
rationale as the sibling fix in
tests/integration/test_decision_service_protected_transfer.py (see that
file's module docstring for the two concrete, orchestrator-reproduced
failure modes: a scavenged destination lot landing on one of
seed/generators/generate.py's own 5%-weighted QUARANTINE draws, and a
scavenged work order another test had already mitigated out from under
this one). The synthetic shortfall (5) is chosen to exactly equal the
quantity this test transfers, so the work_order_risk flip from CRITICAL to
MITIGATED (spec 03's own acceptance line) is exercised deterministically
every run, not merely possible depending on which real work order got
scavenged.
"""

from __future__ import annotations

import httpx
import psycopg
import pytest

from services.common.forensic_queries import run_forensic_query as _run_query
from services.decision_service.execution import action_execution_id_for
from services.projection_builder.reader import get_work_order_risk
from tests.faults.helpers import start_execution, wait_for_terminal_status
from tests.integration.conftest import wait_until
from tests.integration.decision_helpers import create_at_risk_work_order_and_wait

# Reserved synthetic index (see decision_helpers.py's own reserved-range
# comment) and a fixed, clearly-synthetic work_order_id, distinct from the
# sibling protected-transfer fixture's own reserved index so the two files
# never share a synthetic part even when both run in the same session.
_WORK_ORDER_ID = "WO-TEST-H13-01"
_PART_INDEX = 1101
_SHORTFALL = 5  # == the quantity this test transfers, so shortage hits exactly 0 (MITIGATED)


@pytest.fixture()
def at_risk_route(
    mes_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
) -> dict:
    return create_at_risk_work_order_and_wait(
        mes_client,
        wms_client,
        ontology_hot_conn,
        _WORK_ORDER_ID,
        index=_PART_INDEX,
        # Empirically required to be HIGH, even though this file is not
        # testing the protected-transfer gate itself: services/decision_
        # service/evidence.py::_resolve_route_protection only ever populates
        # `route_protection.work_order_ids` for HIGH+at_risk candidates (see
        # its own `if candidate["priority"] == "HIGH" and candidate["at_risk"]`
        # line) — for a MEDIUM/LOW-priority at-risk work order that list is
        # always empty, which deterministically trips
        # gather_transfer_inventory_evidence's `work_order_route_mismatch`
        # check the moment `work_order` is declared (verified live: a MEDIUM
        # version of this fixture reproduced exactly the
        # INSUFFICIENT_EVIDENCE/work_order_route_mismatch failure
        # docs/experiment/briefs/phase10fix.md diagnosed for the ORIGINAL
        # scavenged-route flake, "the product was CORRECT" — the scavenged
        # work order there was similarly no longer a HIGH-priority
        # candidate). Since this test declares `work_order` and asserts
        # APPROVED, HIGH is the only priority that reaches that status.
        priority="HIGH",
        source_warehouse="WH-B",
        destination_warehouse="WH-A",
        shortfall=_SHORTFALL,
        source_on_hand=100,  # >> default_safety_stock (10) + this test's <= 5-unit transfers
    )


def test_h13_queries_6_7_8_and_work_order_risk_flips_to_mitigated(
    decision_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client, at_risk_route: dict
):
    wo_id = at_risk_route["work_order_id"]
    qty = min(at_risk_route["candidate_quantity"], 5)  # small, deterministic; enough to make measurable progress
    before = get_work_order_risk(ontology_hot_conn, wo_id)
    assert before is not None and before["at_risk"] is True

    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {
                "source_warehouse": at_risk_route["source_warehouse"],
                "destination_warehouse": at_risk_route["destination_warehouse"],
                "part": at_risk_route["part"],
                "quantity": qty,
                "work_order": wo_id,
            },
            "context": {},
        },
    )
    assert r.status_code == 200, r.text
    decision = r.json()
    assert decision["status"] == "APPROVED", decision
    decision_id = decision["decision_id"]

    start_execution(decision_client, decision_id)
    final = wait_for_terminal_status(decision_client, decision_id)
    assert final["status"] == "OBSERVED_SUCCESS", final

    action_execution_id = action_execution_id_for(decision_id)

    # --- H13 query 6: which external objects changed ---
    q6 = _run_query(rdf4j_client, "q6_which_external_objects_changed.rq", decision_id)
    assert len(q6) == 1
    assert q6[0]["actionExecutionId"] == action_execution_id
    assert q6[0]["externalSystem"] == "WMS"
    assert q6[0]["commandStatus"] == "200"
    assert int(q6[0]["quantity"]) == qty

    # --- H13 query 7: what outcome was actually observed ---
    q7 = _run_query(rdf4j_client, "q7_what_outcome_was_observed.rq", decision_id)
    assert len(q7) == 1
    assert q7[0]["reconciliationState"] == "CONVERGED"
    assert q7[0]["outcomeId"] == f"O-{action_execution_id}"

    # --- spec 03: work_order_risk critical -> mitigated (or shortage strictly decreased) ---
    def _progressed():
        after = get_work_order_risk(ontology_hot_conn, wo_id)
        return after if (after is not None and after["shortage"] < before["shortage"]) else None

    after = wait_until(_progressed, timeout_s=30.0)
    assert after is not None, f"work_order_risk for {wo_id} never reflected the {qty}-unit mitigation"
    assert after["shortage"] == before["shortage"] - qty
    if after["shortage"] == 0:
        assert after["at_risk"] is False
        assert after["severity"] == "MITIGATED"

    # --- H13 query 8: which later decisions depended on that outcome ---
    # Propose (but don't execute) a SECOND decision concerning the SAME work
    # order, created strictly after the first — the "later decision".
    r2 = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {
                "source_warehouse": at_risk_route["source_warehouse"],
                "destination_warehouse": at_risk_route["destination_warehouse"],
                "part": at_risk_route["part"],
                "quantity": 1,
                "work_order": wo_id,
            },
            "context": {},
        },
    )
    assert r2.status_code == 200, r2.text
    later_decision_id = r2.json()["decision_id"]

    q8 = _run_query(rdf4j_client, "q8_which_later_decisions_depended_on_outcome.rq", decision_id)
    later_ids = {row["laterDecisionId"] for row in q8}
    assert later_decision_id in later_ids, (later_decision_id, later_ids)
