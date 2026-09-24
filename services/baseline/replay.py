"""Historical replay for the baseline variant — "implement whatever replay
it can do honestly with relational structures; if it can't reach parity,
record why" (docs/experiment/briefs/phase8.md item 1).

Reuses services/decision_service/replay.py's `_eval_policy` (a pure
"ask the live OPA server, else `opa eval` via docker against the archived
bundle" helper — zero RDF dependency) and `_sha256_of_dir`/`_sha256_of_file`
(archive-integrity hashing, also zero RDF dependency) UNCHANGED.

Where this HONESTLY DIFFERS from services/decision_service/replay.py, and
why (see docs/experiment/implementation-notes.md Phase 8 section for the
full discussion):

  - No ontology/shapes archive to verify (F29's "old contract artifact
    deleted/modified" concern) — this variant's ONLY versioned contract
    artifacts are authorization/policies/identity, all SHARED with the
    ontology variant and verified the identical way.
  - Evidence integrity rests on ONE fewer independent layer: the ontology
    variant's evidence hash is checked against a SEPARATE RDF4J-stored
    EvidenceSnapshot resource (a second copy, written in the same
    transaction as the Decision but a structurally distinct resource) —
    this variant's evidence_snapshot lives in the SAME `decisions` row as
    everything else, so "the evidence hash still matches" here proves the
    JSONB column hasn't been tampered with SINCE INSERT, but does not
    benefit from a second artifact having to independently agree. A real,
    honestly-reported difference in depth of tamper-evidence, not
    parity-by-construction.
  - Authorization replay uses the SAME live-re-Check-with-historical-
    tuple-snapshot mechanism (Phase 7b/ADR 0004) since
    services/baseline/store.py captures the identical fields
    authz.check() already returns for free — genuine parity here, not a
    gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from services.baseline import hashing, store
from services.decision_service import authz, policy as policy_mod
from services.decision_service.action_types import get_action_type
from services.decision_service.replay import (
    ReplayIntegrityError,
    _eval_policy,
    _sha256_of_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = REPO_ROOT / "contracts"


class DecisionNotFound(ValueError):
    pass


@dataclass
class ReplayResult:
    decision_id: str
    original: dict[str, Any]
    replay: dict[str, Any]
    status: str
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "original": self.original, "replay": self.replay,
            "status": self.status, **({"failure_reasons": self.failure_reasons} if self.failure_reasons else {}),
        }


def _parse_version_tag(tag: str) -> tuple[str, str]:
    version, _, sha = tag.partition("@sha256:")
    return version, sha


def _verify_archive(kind: str, version_dir: str, expected_sha: str, pattern: str) -> None:
    directory = CONTRACTS_ROOT / kind / version_dir
    if not directory.is_dir():
        raise ReplayIntegrityError(f"F29: contracts/{kind}/{version_dir}/ no longer exists on disk (pinned sha256={expected_sha})")
    actual = _sha256_of_dir(directory, pattern)
    if actual != expected_sha:
        raise ReplayIntegrityError(
            f"F29: contracts/{kind}/{version_dir}/ content sha256={actual} does not match the pinned sha256={expected_sha}"
        )


def replay_decision(decision_id: str, conn: psycopg.Connection, openfga_api_url: str, opa_base_url: str | None = None) -> ReplayResult:
    row = store.get_decision(conn, decision_id)
    if row is None:
        raise DecisionNotFound(f"decision {decision_id!r} not found")

    evidence_snapshot = row["evidence_snapshot"] or {}
    recomputed_evidence_hash = hashing.evidence_snapshot_content_hash(
        evidence_snapshot.get("facts_used", {}), evidence_snapshot.get("source_positions", []),
        evidence_snapshot.get("projection_row_hashes", []),
    )
    stored_evidence_hash = evidence_snapshot.get("content_hash")
    evidence_hash_match = stored_evidence_hash is not None and recomputed_evidence_hash == stored_evidence_hash

    parameters = row["parameters"]
    recomputed_decision_hash = hashing.decision_content_hash(
        row["actor_type"], row["actor_id"], row["principal_actor_id"], row["evidence_snapshot_id"],
        row["authorization_model_version"], row["policy_bundle_version"], row["action_type"], row["action_version"], parameters,
    )
    stored_decision_hash = row["decision_content_hash"]
    action_input_match = True if stored_decision_hash is None else recomputed_decision_hash == stored_decision_hash

    policy_vdir, policy_sha = _parse_version_tag(row["policy_bundle_version"])
    authz_vdir, authz_sha = _parse_version_tag(row["authorization_model_version"])
    _verify_archive("policies", policy_vdir, policy_sha, "*")
    _verify_archive("authorization", authz_vdir, authz_sha, "model.fga")

    authz_row = row["authorization_result"]
    policy_row = row["policy_result"]

    policy_was_unavailable = (policy_row or {}).get("outcome") == policy_mod.UNAVAILABLE
    authz_was_unavailable = (authz_row or {}).get("outcome") == authz.UNAVAILABLE
    gate_was_unavailable = policy_was_unavailable or authz_was_unavailable

    gate_result_match = True
    policy_replayed_outcome = None
    if policy_row is not None and policy_row.get("input_json") is not None and not policy_was_unavailable:
        action = get_action_type(row["action_type"], row["action_version_dir"] or "v1")
        package_path = action.policy_package if action else None
        if package_path:
            policy_replayed_outcome = _eval_policy(opa_base_url, CONTRACTS_ROOT / "policies" / policy_vdir, package_path, policy_row["input_json"])
            if policy_replayed_outcome != policy_row.get("outcome"):
                gate_result_match = False

    authz_replayed_outcome = (authz_row or {}).get("outcome")
    if authz_row is None or not authz_row.get("outcome"):
        authz_replay_mode = "not_applicable"
    elif authz_was_unavailable:
        authz_replay_mode = "not_applicable_outage"
    else:
        authz_replay_mode = "recorded_only"
        model_id = authz_row.get("authorization_model_id")
        tuples_snapshot = authz_row.get("tuples_snapshot")
        if model_id and authz_row.get("relation_or_package") and authz_row.get("object_or_input_hash") and tuples_snapshot:
            store_id = authz.resolve_store_id(openfga_api_url)
            if store_id:
                live = authz.check(
                    openfga_api_url, store_id, authz_row["relation_or_package"], authz_row["object_or_input_hash"],
                    row["actor_type"], row["actor_id"], model_id,
                    contextual_tuples=tuples_snapshot, capture_tuples_snapshot=False,
                )
                if live.outcome != authz.UNAVAILABLE:
                    authz_replay_mode = "live"
                    authz_replayed_outcome = live.outcome
                    if live.outcome != authz_row.get("outcome"):
                        gate_result_match = False

    FAIL_CLOSED_STATUSES = {
        "GATE_UNAVAILABLE", "DENIED_AUTHORIZATION", "DENIED_POLICY",
        "INSUFFICIENT_EVIDENCE",
    }
    zero_effects_linked = True
    if gate_was_unavailable:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM action_executions WHERE decision_id = %s LIMIT 1", (decision_id,))
            zero_effects_linked = cur.fetchone() is None

    all_pass = evidence_hash_match and action_input_match and gate_result_match
    failure_reasons = []
    if not evidence_hash_match:
        failure_reasons.append("evidence_hash_mismatch")
    if not action_input_match:
        failure_reasons.append("decision_content_hash_mismatch")
    if not gate_result_match:
        failure_reasons.append("gate_result_mismatch")
    if authz_replay_mode == "recorded_only":
        failure_reasons.append("authz_replay_recorded_only")
    if gate_was_unavailable and not zero_effects_linked:
        failure_reasons.append("gate_unavailable_but_effects_linked")
    if gate_was_unavailable and row["status"] not in FAIL_CLOSED_STATUSES:
        failure_reasons.append("gate_unavailable_but_status_not_fail_closed")

    if gate_was_unavailable:
        fail_closed_verified = evidence_hash_match and action_input_match and zero_effects_linked and row["status"] in FAIL_CLOSED_STATUSES
        status = "PASS_FAIL_CLOSED_VERIFIED" if fail_closed_verified else "FAIL"
    elif not all_pass:
        status = "FAIL"
    elif authz_replay_mode == "recorded_only":
        status = "PARTIAL_RECORDED_ONLY"
    else:
        status = "PASS"

    return ReplayResult(
        decision_id=decision_id,
        original={
            "evidence_hash": stored_evidence_hash,
            "authz_version": row["authorization_model_version"],
            "policy_version": row["policy_bundle_version"],
            "action_version": f"{row['action_version_dir']}@{row['action_pinned_sha256']}",
            "gate_results": {"authorization": (authz_row or {}).get("outcome"), "policy": (policy_row or {}).get("outcome")},
            "proposed_action": {"action_type": row["action_type"], "parameters": parameters},
            "observed_outcome": row["status"],
        },
        replay={
            "reconstructed": True,
            "evidence_hash_match": evidence_hash_match,
            "gate_result_match": gate_result_match,
            "action_input_match": action_input_match,
            "policy_replayed_outcome": policy_replayed_outcome,
            "authz_replayed_outcome": authz_replayed_outcome,
            "authz_replay_mode": authz_replay_mode,
            "gate_was_unavailable": gate_was_unavailable,
            "zero_effects_linked": zero_effects_linked if gate_was_unavailable else None,
        },
        status=status,
        failure_reasons=failure_reasons,
    )
