"""F29-style test for the Phase 7b tuple snapshot (docs/adr/0004
"Update (Phase 7b)"): a decision's own `oo:checkTuplesSnapshotJson` — the
historical relationship-tuple snapshot `services/decision_service/replay.py`
replays back to OpenFGA as `contextual_tuples` — is not just stored and
cited, it is actually EXERCISED by the live re-Check. Removing the one
tuple that grants the recorded ALLOWED outcome from the snapshot flips the
live-replayed outcome to DENIED, which must make replay FAIL loudly
(`gate_result_mismatch`), never a silent pass-through. Restores the
original snapshot in `finally` and re-verifies PASS again — same
mutate-then-restore discipline as tests/replay/test_f29_replay_integrity.py
(the archived-policy-file variant of the same F29 requirement).
"""

from __future__ import annotations

from services.common.rdf_graphs import decision_graph_iri, oo_instance_iri
from services.common.sparql_escape import escape_sparql_literal
from services.decision_service.hashing import canonical_json
from services.decision_service.replay import replay_decision

OO = "https://example.local/oo/"


def _find_live_allowed_decision(decision_ids, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    """Scans the corpus for one decision whose authorization already
    replayed PASS with authz_replay_mode == 'live' and outcome == ALLOWED
    — the shape this test needs (tampering an ALREADY-DENIED check's
    snapshot to an empty tuple list can never observably flip anything).
    Job order within the corpus is non-deterministic (historical_corpus.py
    generates via a thread pool, so decision_ids order is completion
    order, not job-kind order) — scan rather than assume a fixed index."""
    for decision_id in decision_ids:
        result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
        if (
            result.status == "PASS"
            and result.replay["authz_replay_mode"] == "live"
            and result.replay["authz_replayed_outcome"] == "ALLOWED"
        ):
            return decision_id
    return None


def _read_snapshot_json(rdf4j_client, check_iri: str) -> str:
    rows = rdf4j_client.select(f"""
PREFIX oo: <{OO}>
SELECT ?json WHERE {{ <{check_iri}> oo:checkTuplesSnapshotJson ?json . }}
""")
    assert rows, f"no oo:checkTuplesSnapshotJson found for {check_iri} — nothing to tamper with"
    return rows[0]["json"]


def _replace_snapshot_json(rdf4j_client, graph_iri: str, check_iri: str, new_json: str) -> None:
    safe = escape_sparql_literal(new_json)
    sparql = f"""
PREFIX oo: <{OO}>
DELETE {{ GRAPH <{graph_iri}> {{ <{check_iri}> oo:checkTuplesSnapshotJson ?old . }} }}
INSERT {{ GRAPH <{graph_iri}> {{ <{check_iri}> oo:checkTuplesSnapshotJson "{safe}" . }} }}
WHERE {{ GRAPH <{graph_iri}> {{ <{check_iri}> oo:checkTuplesSnapshotJson ?old . }} }}
"""
    resp = rdf4j_client.update(sparql)
    assert resp.status_code in (200, 204), f"SPARQL UPDATE failed: {resp.status_code} {resp.text[:300]}"


def test_f29_tampered_tuple_snapshot_makes_replay_fail_loudly(
    historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url,
):
    decision_id = _find_live_allowed_decision(
        historical_corpus["v1"]["decision_ids"], ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url,
    )
    assert decision_id is not None, (
        "expected at least one V1 decision whose authorization replays PASS with authz_replay_mode == 'live' "
        "and outcome ALLOWED — the regenerated Phase 7b corpus should have plenty (every planner-1 'normal' job)"
    )

    graph_iri = decision_graph_iri(decision_id)
    check_iri = oo_instance_iri("AuthorizationCheck", decision_id)
    original_json = _read_snapshot_json(rdf4j_client, check_iri)

    try:
        # "tamper": replace the recorded tuple snapshot with an EMPTY tuple
        # set — the grant tuple(s) that made the original Check resolve
        # ALLOWED are gone, so the live re-Check (run WITH this snapshot as
        # contextual_tuples) must now resolve DENIED.
        _replace_snapshot_json(rdf4j_client, graph_iri, check_iri, canonical_json([]))

        tampered = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
        assert tampered.status == "FAIL", tampered.as_dict()
        assert "gate_result_mismatch" in tampered.failure_reasons, tampered.as_dict()
        assert tampered.replay["authz_replay_mode"] == "live", tampered.as_dict()
        assert tampered.replay["authz_replayed_outcome"] == "DENIED", tampered.as_dict()
    finally:
        _replace_snapshot_json(rdf4j_client, graph_iri, check_iri, original_json)

    # Restored: the SAME decision replays PASS/live/ALLOWED again — proves
    # the failure above was genuinely caused by the tampered snapshot, not
    # some other drift.
    restored = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    assert restored.status == "PASS", restored.as_dict()
    assert restored.replay["authz_replay_mode"] == "live", restored.as_dict()
    assert restored.replay["authz_replayed_outcome"] == "ALLOWED", restored.as_dict()
