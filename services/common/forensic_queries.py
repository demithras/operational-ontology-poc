"""Shared H13 forensic-query loader (contracts/queries/v1/q1-q9).

Phase 9 step 0b: q9 already substituted both %%DECISION_ID%% and
%%GRAPH_IRI%% (services/decision_service/replay.py, Phase 7b fix) — q1-q8
did not, and once the historical corpus reached ~5k decisions, q5's
unscoped ?proposer/?approver/?executor oo:actorId joins against a shared
actor node re-asserted in every decision's own graph produced an
N-per-shared-node fan-out that hit httpx.ReadTimeout
(test_forensic_query_5_traces_delegation_and_approval). contracts/queries/v1/
q1-q8.rq now all carry a %%GRAPH_IRI%% placeholder too (see each file's own
header comment). This module is the ONE place that substitutes both, so no
future caller can reintroduce an unscoped copy the way three separate
`_run_query` helpers previously each hand-rolled the %%DECISION_ID%%-only
substitution.
"""

from __future__ import annotations

from pathlib import Path

from services.common.rdf_graphs import decision_graph_iri
from services.common.sparql_escape import escape_sparql_literal

QUERIES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "queries" / "v1"


def run_forensic_query(rdf4j_client, name: str, decision_id: str) -> list[dict]:
    """Load contracts/queries/v1/<name>, substitute %%DECISION_ID%% and
    %%GRAPH_IRI%% for `decision_id`, and run it against `rdf4j_client`.

    `name` is one of q1_why_was_decision_made.rq .. q9_replay_authz_fields.rq
    (or any future addition following the same two-placeholder convention).
    """
    template = (QUERIES_DIR / name).read_text()
    sparql = template.replace("%%DECISION_ID%%", escape_sparql_literal(decision_id))
    sparql = sparql.replace("%%GRAPH_IRI%%", decision_graph_iri(decision_id))
    return rdf4j_client.select(sparql)
