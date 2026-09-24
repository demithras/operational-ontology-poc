"""H13 (docs/experiment/spec/01_hypotheses.md: "Provenance is queryable,
not merely logged") for a V1 decision, queried AFTER the V1->V2->V3
migration sequence has run — proving the SAME contracts/queries/v1/*.rq
SPARQL (unchanged, generic across contract versions by design — they query
oo: governance predicates, never fac: domain predicates that evolved)
still answers every forensic question about an OLD decision once the live
system has moved on. This is acceptance criterion B.10 combined with B.8/B.9:
a forensic query is not just possible once, it survives contract evolution.
"""

from __future__ import annotations

import re

from services.common.forensic_queries import run_forensic_query as _run_query


def test_forensic_queries_1_through_5_answer_for_v1_decision_after_v3_migration(historical_corpus, rdf4j_client):
    decision_id = historical_corpus["v1"]["decision_ids"][0]

    q1 = _run_query(rdf4j_client, "q1_why_was_decision_made.rq", decision_id)
    assert len(q1) == 1, "H13 Q1 (why was decision made) must answer for a V1 decision post-migration"
    assert q1[0]["status"] in ("Approved", "ObservedSuccess", "Diverged", "OutcomeUnknown", "DeniedPolicy", "DeniedAuthorization", "InsufficientEvidence")

    q2 = _run_query(rdf4j_client, "q2_which_evidence_was_used.rq", decision_id)
    assert len(q2) == 1, "H13 Q2 (which evidence was used)"

    q3 = _run_query(rdf4j_client, "q3_which_evidence_was_excluded.rq", decision_id)
    assert len(q3) == 1, "H13 Q3 (which evidence was available but excluded)"

    q4 = _run_query(rdf4j_client, "q4_which_policy_and_authz_versions.rq", decision_id)
    assert len(q4) == 1, "H13 Q4 (which policy/authz versions)"
    # The decision itself still reports its OWN, original v1 pin — never
    # silently migrated to whatever is live now (the whole point of H7).
    assert q4[0]["policyBundleVersion"].startswith("v1@sha256:"), q4[0]["policyBundleVersion"]
    assert re.match(r"^v\d+@sha256:[0-9a-f]{64}$", q4[0]["authorizationModelVersion"])

    q5 = _run_query(rdf4j_client, "q5_who_proposed_approved_executed.rq", decision_id)
    assert len(q5) == 1, "H13 Q5 (who proposed/approved/executed)"
    assert q5[0]["proposerId"] == "planner-1"


def test_forensic_queries_6_through_8_answer_for_a_v1_executed_decision_after_v3_migration(
    historical_corpus, rdf4j_client,
):
    """Q6-8 need a decision that actually EXECUTED (external objects
    changed / outcome observed / downstream dependents) — pick the first
    V1 corpus decision whose recorded status is OBSERVED_SUCCESS."""
    import psycopg

    from seed import db_env

    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT decision_id FROM decisions WHERE status = 'OBSERVED_SUCCESS' AND decision_id = ANY(%s) LIMIT 1",
                (historical_corpus["v1"]["decision_ids"],),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None, "expected at least one OBSERVED_SUCCESS V1 corpus decision"
    decision_id = row[0]

    q6 = _run_query(rdf4j_client, "q6_which_external_objects_changed.rq", decision_id)
    assert len(q6) >= 1, "H13 Q6 (which external objects changed)"

    q7 = _run_query(rdf4j_client, "q7_what_outcome_was_observed.rq", decision_id)
    assert len(q7) == 1, "H13 Q7 (what outcome was observed)"

    # Q8 ("which later decisions depended on that outcome") legitimately
    # returns zero rows for most decisions (nothing downstream referenced
    # it) — H13 only requires the query itself to be ANSWERABLE (run
    # without error and return a well-formed, if possibly empty, result),
    # not that every decision has a non-empty dependent set.
    q8 = _run_query(rdf4j_client, "q8_which_later_decisions_depended_on_outcome.rq", decision_id)
    assert isinstance(q8, list)
