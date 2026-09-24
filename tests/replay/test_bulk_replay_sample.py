"""Phase 7b requirement C: "add a test that replays a random sample of
>= 300 bulk decisions -> 100% PASS with live authz replay." Samples
`D-BULK*` decisions (seed/generators/bulk_historical_decisions.py) —
decision_id's own uuid4 suffix already makes lexicographic order an
effectively random, but reproducible, sample; no separate RNG needed.

Every bulk record's gate outcomes are now REAL evaluations (real OpenFGA
Check, real `opa eval`, see bulk_historical_decisions.py's module
docstring for what changed from Phase 7), so this corpus is held to the
SAME bar as the live corpus (tests/replay/test_replay_corpus.py): 100%
PASS, and authz_replay_mode == "live" for every decision that has an
authorization check.
"""

from __future__ import annotations

import pytest

from services.decision_service.replay import replay_decision

SAMPLE_SIZE = 500  # comfortably over the spec's ">= 300" floor


@pytest.fixture()
def bulk_decision_sample(ontology_hot_conn) -> list[str]:
    with ontology_hot_conn.cursor() as cur:
        cur.execute(
            "SELECT decision_id FROM decisions WHERE decision_id LIKE 'D-BULK%' ORDER BY decision_id LIMIT %s",
            (SAMPLE_SIZE,),
        )
        ids = [row[0] for row in cur.fetchall()]
    if not ids:
        pytest.skip(
            "no D-BULK* decisions found — run seed/generators/bulk_historical_decisions.py first "
            "(see docs/experiment/implementation-notes.md Phase 7b section)"
        )
    return ids


def test_bulk_sample_replays_pass_with_live_authz(bulk_decision_sample, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url):
    assert len(bulk_decision_sample) >= 300, f"expected >= 300 bulk decisions to sample, got {len(bulk_decision_sample)}"

    results = []
    for decision_id in bulk_decision_sample:
        result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
        results.append((decision_id, result.status, result.replay["authz_replay_mode"], result.failure_reasons))

    failures = [(d, s, reasons) for d, s, mode, reasons in results if s != "PASS"]
    assert not failures, f"{len(failures)}/{len(results)} bulk decisions did not replay PASS: {failures[:10]}"

    checked = [(d, mode) for d, s, mode, _ in results if mode != "not_applicable"]
    assert checked, "expected at least one sampled bulk decision with an authorization check"
    non_live = [(d, mode) for d, mode in checked if mode != "live"]
    assert not non_live, (
        f"{len(non_live)}/{len(checked)} bulk decisions with an authorization check did not achieve "
        f"authz_replay_mode == 'live': {non_live[:10]}"
    )
