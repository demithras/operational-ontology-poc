"""Content hashes for the baseline variant — reuses
services/decision_service/hashing.py's canonical_json/sha256_of verbatim
(pure functions, no storage dependency); `decision_content_hash` is
adapted to drop the ontology_version/shape_set_version fields this variant
has no equivalent of."""

from __future__ import annotations

from typing import Any

from services.decision_service.hashing import canonical_json, sha256_of  # noqa: F401 (re-exported)


def evidence_snapshot_content_hash(facts_used: dict, source_positions: list[dict], projection_row_hashes: list[str]) -> str:
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
    authorization_model_version: str,
    policy_bundle_version: str,
    action_type: str,
    action_version: int,
    parameters: dict[str, Any],
) -> str:
    """Same role/exclusions as services/decision_service/hashing.py's
    decision_content_hash (identifies WHAT WAS PROPOSED, never gate
    results/timestamps) — minus ontology_version/shape_set_version, which
    this variant has no equivalent of."""
    payload = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "principal_actor_id": principal_actor_id,
        "evidence_snapshot_id": evidence_snapshot_id,
        "authorization_model_version": authorization_model_version,
        "policy_bundle_version": policy_bundle_version,
        "action_type": action_type,
        "action_version": action_version,
        "parameters": parameters,
    }
    return sha256_of(payload)
