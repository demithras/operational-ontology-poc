"""`make test-replay` (docs/experiment/spec/07_versioning_and_replay.md
"replay(all V1 decisions); replay(all V2 decisions)" — "V1 decisions
replay successfully after V3 migration", acceptance criterion B.8/B.9):
replays every decision seed/generators/historical_corpus.py recorded for
V1 and V2, under whatever contract version is CURRENTLY deployed (this
experiment leaves the stack at V3 — see
docs/experiment/implementation-notes.md Phase 7 section). 100% PASS
required — a single FAIL fails this whole test, never averaged away.

Phase 7b (docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md's
"Update (Phase 7b)"): PASS alone is no longer sufficient proof for
authorization — a decision that only achieved the honest
"recorded_only" fallback reports `PARTIAL_RECORDED_ONLY`, not `PASS` (see
services/decision_service/replay.py). This corpus was regenerated on the
post-persistence-fix (postgres-datastore) OpenFGA store specifically so
every decision's authorization_model_id resolves live AND its
oo:checkTuplesSnapshotJson lets replay re-Check against the historical
tuples as contextual_tuples — so `authz_replay_mode == "live"` is required
for every decision that actually went through an authorization check (a
minority of jobs, e.g. INSUFFICIENT_EVIDENCE ones, never reach a check at
all — those report "not_applicable", not "live", and are excluded from
that specific assertion, not from the PASS requirement).
"""

from __future__ import annotations

from services.decision_service.replay import replay_decision


def _replay_all(decision_ids: list[str], ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url) -> list[tuple[str, str, str, list[str]]]:
    results = []
    for decision_id in decision_ids:
        result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
        results.append((decision_id, result.status, result.replay["authz_replay_mode"], result.failure_reasons))
    return results


#: Phase 8 step 0: a decision whose ORIGINAL gate outcome was itself
#: UNAVAILABLE (a real, resolved dependency outage at propose() time)
#: replays as PASS_FAIL_CLOSED_VERIFIED, not PASS — see
#: services/decision_service/replay.py's ReplayResult.status docstring.
#: Neither this tracked live/bulk corpus nor its generation scripts ever
#: run through a real outage, so this set is expected to stay empty for
#: this corpus specifically; it is accepted here (rather than asserted
#: empty) so this test documents the acceptable statuses without assuming
#: how the corpus was generated.
_ACCEPTABLE_STATUSES = {"PASS", "PASS_FAIL_CLOSED_VERIFIED"}


def _assert_all_pass_and_live(results: list[tuple[str, str, str, list[str]]], label: str) -> None:
    failures = [(d, s, reasons) for d, s, mode, reasons in results if s not in _ACCEPTABLE_STATUSES]
    assert not failures, f"{len(failures)}/{len(results)} {label} decisions did not replay PASS: {failures[:10]}"
    checked = [(d, mode) for d, s, mode, _ in results if mode not in ("not_applicable", "not_applicable_outage")]
    assert checked, f"expected at least one {label} decision with an authorization check to replay"
    non_live = [(d, mode) for d, mode in checked if mode != "live"]
    assert not non_live, (
        f"{len(non_live)}/{len(checked)} {label} decisions with an authorization check did not achieve "
        f"authz_replay_mode == 'live' (R4/ADR 0004 requires 100% live for the regenerated corpus): {non_live[:10]}"
    )


def test_all_v1_decisions_replay_pass(historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    decision_ids = historical_corpus["v1"]["decision_ids"]
    assert len(decision_ids) >= 100, f"expected >= 100 V1 decisions, got {len(decision_ids)}"
    results = _replay_all(decision_ids, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    _assert_all_pass_and_live(results, "V1")


def test_all_v2_decisions_replay_pass(historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    decision_ids = historical_corpus["v2"]["decision_ids"]
    assert len(decision_ids) >= 100, f"expected >= 100 V2 decisions, got {len(decision_ids)}"
    results = _replay_all(decision_ids, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    _assert_all_pass_and_live(results, "V2")


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
