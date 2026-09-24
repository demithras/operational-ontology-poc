"""F29 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"old policy deleted -> replay -> replay fails loudly; experiment
considered failed").

Mutates a REAL, archived V1 policy file that a REAL V1 corpus decision
pinned (contracts/manifests/current.json-style content-addressed pinning,
services/decision_service/replay.py's `_verify_archive`) and proves replay
raises loudly (ReplayIntegrityError / HTTP 409), never silently substitutes
the current file or reports a false PASS. Restores the file in `finally` —
same mutate-then-restore pattern as tests/faults/test_action_version_pinning.py
(F34) — so this test never leaves the repo, or `make test-replay`, broken
for any other decision pinned to the same version.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.decision_service.replay import ReplayIntegrityError, replay_decision

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "contracts" / "policies" / "v1" / "transfer_inventory.rego"


def test_f29_deleted_archived_policy_makes_replay_fail_loudly(
    historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url,
):
    decision_id = historical_corpus["v1"]["decision_ids"][0]

    # Sanity: this decision replays PASS before we touch anything.
    baseline = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    assert baseline.status == "PASS", baseline.as_dict()

    original_bytes = POLICY_FILE.read_bytes()
    try:
        POLICY_FILE.unlink()  # "old policy deleted"
        with pytest.raises(ReplayIntegrityError, match="F29"):
            replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    finally:
        POLICY_FILE.write_bytes(original_bytes)

    # Restored: the SAME decision replays PASS again — proves the failure
    # above was genuinely caused by the deletion, not some other drift.
    restored = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    assert restored.status == "PASS", restored.as_dict()


def test_f29_modified_archived_policy_makes_replay_fail_loudly(
    historical_corpus, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url,
):
    """"deleted" per the matrix's own wording, but a REPLACED (mutated)
    archived artifact is the same class of failure — same F29 requirement,
    covered explicitly since it is the more likely real-world accident
    (an edit, not a deletion)."""
    decision_id = historical_corpus["v1"]["decision_ids"][1]
    original_bytes = POLICY_FILE.read_bytes()
    try:
        POLICY_FILE.write_bytes(original_bytes + b"\n# F29 test: tampering with an archived, immutable artifact\n")
        with pytest.raises(ReplayIntegrityError, match="F29"):
            replay_decision(decision_id, ontology_hot_conn, rdf4j_client, openfga_api_url, opa_base_url)
    finally:
        POLICY_FILE.write_bytes(original_bytes)
