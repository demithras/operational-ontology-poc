"""Shared contract-version constants + the Phase 7 "what is deployed right
now, per contract kind" pointer (docs/experiment/spec/07_versioning_and_replay.md).

Phase 5/6 had exactly one ontology contract on disk (contracts/ontology/v1/)
and this file exported a single hardcoded ONTOLOGY_CONTRACT_VERSION = "v1"
constant. Phase 7 introduces v2/v3 directories under several
contracts/<kind>/ trees (ontology, shapes, actions, policies, authorization,
identity, projections) — contracts/manifests/deployed_version.json now
records, per kind, which version directory is CURRENTLY LIVE. "Deploying" a
new contract version is a data-only edit to that one file plus a restart of
whichever process reads it (services/decision_service/manifest.py at
startup; services/projection_builder for its own ontology-version stamp) —
no image rebuild, the same bind-mount pattern services/action_worker
already established for F34 (docker-compose.yml's
`./contracts:/app/contracts:ro`).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"

_DEFAULT_DEPLOYED_VERSION = {
    "ontology": "v1",
    "shapes": "v1",
    "actions": "v1",
    "policies": "v1",
    "authorization": "v1",
    "identity": "v1",
    "projections": "v1",
    "reconciliation": "v1",
}


def deployed_version() -> dict[str, str]:
    """Reads contracts/manifests/deployed_version.json fresh off disk on
    EVERY call — never cached in-process — so a redeploy (edit the file,
    restart the reading process) always takes effect, same "never cache
    across requests" policy services/decision_service/app.py::_current_store_id
    already established for OpenFGA store resolution. Falls back to the
    all-v1 default if the file (or a process's bind mount of it) is
    unavailable, preserving every Phase 1-6 caller's existing v1-only
    behavior exactly — a process that hasn't been given the ./contracts
    mount yet (or is running a unit test with no repo checkout at that
    exact path) must never crash just for asking what's deployed."""
    try:
        raw = json.loads(DEPLOYED_VERSION_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_DEPLOYED_VERSION)
    return {k: raw.get(k, v) for k, v in _DEFAULT_DEPLOYED_VERSION.items()}


def ontology_contract_version() -> str:
    return deployed_version()["ontology"]


# Backward-compatible module-level constant (services/projection_builder/writer.py
# stamps every hot-projection row with this) — resolved once at import time,
# matching that module's existing "computed once, at process start" style.
# A process that must observe a live redeploy without restarting should call
# ontology_contract_version() directly instead of reading this constant.
ONTOLOGY_CONTRACT_VERSION = ontology_contract_version()
