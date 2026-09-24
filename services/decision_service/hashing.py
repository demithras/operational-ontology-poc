"""Content hashes for evidence snapshots and decisions — same canonical-JSON
sha256 pattern as services/projection_builder/hashing.py.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def evidence_snapshot_content_hash(facts_used: dict, source_positions: list[dict], projection_row_hashes: list[str]) -> str:
    """docs/experiment/spec/14_risks_and_open_questions.md R5 hybrid
    manifest: hashes over the frozen required facts + source positions +
    projection row hashes."""
    payload = {
        "facts_used": facts_used,
        "source_positions": sorted(source_positions, key=canonical_json),
        "projection_row_hashes": sorted(projection_row_hashes),
    }
    return sha256_of(payload)


def decision_content_hash(
    actor_type: str,
    actor_id: str,
    principal_actor_id: str | None,
    evidence_snapshot_id: str,
    ontology_version: str,
    shape_set_version: str,
    authorization_model_version: str,
    policy_bundle_version: str,
    action_type: str,
    action_version: int,
    parameters: dict,
) -> str:
    """docs/experiment/spec/06_decision_and_action_runtime.md execute():
    "verify immutable content hash"; F33: approval must be checked against
    this exact value. Deliberately excludes `status`/gate RESULTS/timestamps
    — this hash identifies WHAT WAS PROPOSED (the immutable tuple), not what
    the gates decided about it, so re-evaluating the same proposal never
    changes it."""
    payload = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "principal_actor_id": principal_actor_id,
        "evidence_snapshot_id": evidence_snapshot_id,
        "ontology_version": ontology_version,
        "shape_set_version": shape_set_version,
        "authorization_model_version": authorization_model_version,
        "policy_bundle_version": policy_bundle_version,
        "action_type": action_type,
        "action_version": action_version,
        "parameters": parameters,
    }
    return sha256_of(payload)
