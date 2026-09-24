"""Phase 9 step 0b — the scaling proof this fix's own guarantee rests on:
"with the full corpus loaded, every q1-q9 finishes in < 2s for a decision
by the busiest actor."

The busiest actor is the worst case for the exact fan-out class this fix
closes (see contracts/queries/v1/q5's header comment and
services/common/forensic_queries.py's docstring): a shared actor node's
oo:actorId triple is re-asserted once per decision that actor ever
proposed/approved/executed, so the MORE decisions one actor accumulates,
the larger an unscoped join's would-be fan-out — this test exercises that
actor specifically, not an arbitrary one, and would have caught the
httpx.ReadTimeout the orchestrator's Phase 8 review reported.

Skips (not fails) if the corpus is too small to be a meaningful proof —
this is a scaling regression test, not a correctness test (correctness is
tests/integration/test_forensic_queries.py /
tests/integration/test_forensic_queries_phase6.py, which run against a
tiny fresh-decision corpus and would pass trivially fast regardless of
this fix).
"""

from __future__ import annotations

import time

import psycopg
import pytest
from psycopg.rows import dict_row

from services.common.forensic_queries import run_forensic_query

MIN_CORPUS_SIZE = 1000
BUDGET_S = 2.0
QUERY_NAMES = [f"q{n}_{suffix}.rq" for n, suffix in [
    (1, "why_was_decision_made"),
    (2, "which_evidence_was_used"),
    (3, "which_evidence_was_excluded"),
    (4, "which_policy_and_authz_versions"),
    (5, "who_proposed_approved_executed"),
    (6, "which_external_objects_changed"),
    (7, "what_outcome_was_observed"),
    (8, "which_later_decisions_depended_on_outcome"),
    (9, "replay_authz_fields"),
]]


def _busiest_actor_decision_id(conn: psycopg.Connection) -> tuple[str, str, int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT actor_id, COUNT(*) AS n FROM decisions GROUP BY actor_id ORDER BY n DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "", "", 0
        actor_id, n = row["actor_id"], row["n"]
        # Prefer a decision that also has an approval/execution chain so
        # every one of q1-q9's OPTIONAL blocks has something real to
        # traverse, not just the propose-time fields.
        cur.execute(
            "SELECT decision_id FROM decisions WHERE actor_id = %s AND approved_by IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (actor_id,),
        )
        row2 = cur.fetchone()
        if row2 is None:
            cur.execute(
                "SELECT decision_id FROM decisions WHERE actor_id = %s ORDER BY created_at DESC LIMIT 1",
                (actor_id,),
            )
            row2 = cur.fetchone()
        return actor_id, row2["decision_id"], n


def test_forensic_queries_scale_for_the_busiest_actor(ontology_hot_conn: psycopg.Connection, rdf4j_client):
    with ontology_hot_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM decisions")
        total = cur.fetchone()[0]
    if total < MIN_CORPUS_SIZE:
        pytest.skip(
            f"only {total} decisions loaded (< {MIN_CORPUS_SIZE}) — run the Phase 7b historical-corpus "
            "rebuild sequence first (docs/experiment/implementation-notes.md Phase 9 step 0c) for this "
            "scaling proof to be meaningful"
        )

    actor_id, decision_id, actor_decision_count = _busiest_actor_decision_id(ontology_hot_conn)
    assert decision_id, f"no decision found for the busiest actor (total decisions={total})"

    timings: dict[str, float] = {}
    for name in QUERY_NAMES:
        start = time.monotonic()
        rows = run_forensic_query(rdf4j_client, name, decision_id)
        elapsed = time.monotonic() - start
        timings[name] = elapsed
        assert len(rows) <= 50, (
            f"{name} returned {len(rows)} rows for one decision — looks like an unscoped fan-out, "
            f"not a real answer (decision_id={decision_id}, actor={actor_id})"
        )
        assert elapsed < BUDGET_S, (
            f"{name} took {elapsed:.3f}s (budget {BUDGET_S}s) for a decision by the busiest actor "
            f"({actor_id}, {actor_decision_count} decisions) — likely an unscoped shared-node join; "
            f"see contracts/queries/v1/q5's header comment"
        )

    print(
        f"busiest actor={actor_id} ({actor_decision_count} decisions), decision_id={decision_id}, "
        f"corpus size={total}, per-query timings(s)={timings}"
    )
