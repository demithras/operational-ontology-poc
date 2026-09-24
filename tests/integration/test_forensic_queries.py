"""H13 — 'Provenance is queryable, not merely logged.' Runs the 5 stable
SPARQL queries in contracts/queries/v1/*.rq (queries 6-8 complete in
Phase 6 per phase5.md item 8) against real, freshly-committed decisions —
proving H13's claim by API/query, never by reading application source or
scraping logs.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import psycopg

from services.common.sparql_escape import escape_sparql_literal
from tests.integration.decision_helpers import propose_with_freshness_retry, set_inventory_and_wait

QUERIES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "queries" / "v1"


def _run_query(rdf4j_client, name: str, decision_id: str) -> list[dict]:
    template = (QUERIES_DIR / name).read_text()
    sparql = template.replace("%%DECISION_ID%%", escape_sparql_literal(decision_id))
    return rdf4j_client.select(sparql)


def _propose_approved(decision_client: httpx.Client, wms_client: httpx.Client, conn: psycopg.Connection, sku: str) -> dict:
    part = set_inventory_and_wait(wms_client, conn, sku, "WH-B", on_hand=200)
    r = propose_with_freshness_retry(
        conn, part, "WH-B",
        lambda: decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 60},
            },
        ),
    )
    assert r.status_code == 200
    return r.json()


def test_all_five_forensic_queries_answer_for_a_real_decision(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client
):
    decision = _propose_approved(decision_client, wms_client, ontology_hot_conn, "SKU-900601")
    decision_id = decision["decision_id"]
    assert decision["status"] == "APPROVED"

    q1 = _run_query(rdf4j_client, "q1_why_was_decision_made.rq", decision_id)
    assert len(q1) == 1
    assert q1[0]["status"] == "Approved"
    assert q1[0]["policyOutcome"] == "allow"
    assert q1[0]["authzOutcome"] == "ALLOWED"
    assert q1[0]["conformanceOutcome"] == "CONFORMS"

    q2 = _run_query(rdf4j_client, "q2_which_evidence_was_used.rq", decision_id)
    assert len(q2) == 1
    assert "current_source_inventory" in q2[0]["requiredFactsJson"]

    q3 = _run_query(rdf4j_client, "q3_which_evidence_was_excluded.rq", decision_id)
    assert len(q3) == 1  # excludedFactsJson is present (possibly "{}") for every decision

    q4 = _run_query(rdf4j_client, "q4_which_policy_and_authz_versions.rq", decision_id)
    assert len(q4) == 1
    # Content-addressed format (spec 05 "Policy references": "records a
    # content-addressed ... version: inventory-policy@sha256:...").
    assert q4[0]["policyBundleVersion"].startswith("v1@sha256:")
    assert q4[0]["authorizationModelVersion"].startswith("v1@sha256:")
    assert q4[0]["checkRelation"] == "can_transfer_inventory"

    q5 = _run_query(rdf4j_client, "q5_who_proposed_approved_executed.rq", decision_id)
    assert len(q5) == 1
    assert q5[0]["proposerId"] == "planner-1"


def test_forensic_query_5_traces_delegation_and_approval(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-900602", "WH-B", on_hand=1000)
    r = propose_with_freshness_retry(
        ontology_hot_conn, part, "WH-B",
        lambda: decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 150},
            },
        ),
    )
    decision = r.json()
    assert decision["status"] == "REQUIRES_APPROVAL"
    approve = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": decision["decision_content_hash"]},
    )
    assert approve.status_code == 200

    q5 = _run_query(rdf4j_client, "q5_who_proposed_approved_executed.rq", decision["decision_id"])
    assert len(q5) == 1
    assert q5[0]["proposerId"] == "planner-1"
    assert q5[0]["approvedById"] == "supervisor-1"
