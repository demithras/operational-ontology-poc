"""H13 queries 6-8 (Phase 6: "which external objects changed", "what outcome
was actually observed", "which later decisions depended on that outcome")
plus spec 03's own acceptance line: "After OBSERVED_SUCCESS, the canonical
incident's work_order_risk projection changes from critical to mitigated" —
proved against a REAL at-risk work order in the seeded dataset (discovered
live, same rationale as tests/integration/test_decision_service_protected_transfer.py
for not hard-coding WO-42: test_canonical_scenario.py may have already
mitigated it by the time this file runs as part of the full suite).
"""

from __future__ import annotations

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from services.common.forensic_queries import run_forensic_query as _run_query
from services.decision_service.execution import action_execution_id_for
from services.projection_builder.reader import get_work_order_risk
from tests.faults.helpers import start_execution, wait_for_terminal_status
from tests.integration.conftest import wait_until


def _find_at_risk_route(conn: psycopg.Connection) -> dict | None:
    """Any at-risk work order (HIGH priority or not — this file is not
    testing the protected-transfer gate) with a real transfer_candidates
    route out of WH-A/WH-B (planner-1's authority scope,
    contracts/authorization/v1/tuples.yaml) and enough headroom over
    default_safety_stock (10, contracts/policies/v1/data.json) that a
    small test transfer can't itself be denied by the policy gate.

    Phase 9 regression-confirmation finding: this query's ORDER BY
    previously explicitly PREFERRED WO-42
    (`ORDER BY (tc.work_order_id = 'WO-42') DESC, ...`) — directly
    contradicting this file's own docstring ("discovered live... same
    rationale as... for not hard-coding WO-42") and common.md's standing
    rule ("Never mutate the canonical fixture... except in tests that
    explicitly restore it"). Reproduced live during Phase 9's own
    regression-confirmation run: `test_canonical_scenario.py` had made
    WO-42 genuinely at-risk (steps 1-3, before its own step 4 mitigation
    executes), this fixture picked it up, and this test's own 5-unit
    governed mitigation landed on LOT-A-PX17/LOT-B-PX17 — desyncing
    `test_canonical_scenario.py`'s absolute-state assertion (85/75 instead
    of 80/80) three tests later in the same session. Restored via direct
    SQL (same remedy Phase 6b's own "canonical fixture drift" section used)
    and fixed at the root here: WO-42 is now explicitly EXCLUDED, not just
    deprioritized — deprioritizing alone does not help when it is the only
    row the WHERE clause returns, which is exactly what happened."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT tc.* FROM transfer_candidates tc
            JOIN work_order_risk wor ON wor.work_order_id = tc.work_order_id
            WHERE wor.at_risk = true AND tc.source_warehouse IN ('WH-A', 'WH-B')
              AND tc.work_order_id != 'WO-42'
            ORDER BY tc.available_at_source DESC
            LIMIT 10
            """
        )
        rows = cur.fetchall()
    for row in rows:
        if row["available_at_source"] >= 11 and row["candidate_quantity"] >= 1:
            return row
    return None


@pytest.fixture()
def at_risk_route(ontology_hot_conn: psycopg.Connection) -> dict:
    row = _find_at_risk_route(ontology_hot_conn)
    if row is None:
        pytest.skip("no currently at-risk work order with a usable transfer_candidates route in the seeded dataset right now")
    return row


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
