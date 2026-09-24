"""`make test-replay` (docs/experiment/spec/07_versioning_and_replay.md
"replay(all V1 decisions); replay(all V2 decisions)" — "V1 decisions
replay successfully after V3 migration", acceptance criterion B.8/B.9):
replays every decision seed/generators/historical_corpus.py recorded for
V1 and V2, under whatever contract version is CURRENTLY deployed (this
experiment leaves the stack at V3 — see
docs/experiment/implementation-notes.md Phase 7 section). 100% PASS
required — a single FAIL fails this whole test, never averaged away.
"""

from __future__ import annotations

from services.decision_service.replay import replay_decision


def _replay_all(decision_ids: list[str], ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url) -> list[tuple[str, str, list[str]]]:
    results = []
    for decision_id in decision_ids:
        result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
        results.append((decision_id, result.status, result.failure_reasons))
    return results


def test_all_v1_decisions_replay_pass(historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    decision_ids = historical_corpus["v1"]["decision_ids"]
    assert len(decision_ids) >= 100, f"expected >= 100 V1 decisions, got {len(decision_ids)}"
    results = _replay_all(decision_ids, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    failures = [(d, reasons) for d, status, reasons in results if status != "PASS"]
    assert not failures, f"{len(failures)}/{len(results)} V1 decisions failed replay: {failures[:10]}"


def test_all_v2_decisions_replay_pass(historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    decision_ids = historical_corpus["v2"]["decision_ids"]
    assert len(decision_ids) >= 100, f"expected >= 100 V2 decisions, got {len(decision_ids)}"
    results = _replay_all(decision_ids, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    failures = [(d, reasons) for d, status, reasons in results if status != "PASS"]
    assert not failures, f"{len(failures)}/{len(results)} V2 decisions failed replay: {failures[:10]}"


def test_replay_corpus_is_under_v3_deployed_state():
    """H7's own experiment design: replay must run AFTER the V3 migration,
    never against a stack still sitting at V1/V2 — otherwise "replay after
    migration" is untested by construction."""
    from services.common.contract_versions import deployed_version

    live = deployed_version()
    assert live["actions"] == "v3", (
        f"deployed_version.json actions={live['actions']!r} — this test-replay run must happen AFTER "
        "`make deploy-v3` (migrations/v2_to_v3/deploy.py), per spec 07's 'replay ALL V1 and V2 decisions "
        "under the V3-deployed state'"
    )
