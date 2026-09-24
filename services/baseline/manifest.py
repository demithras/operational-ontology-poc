"""Phase 8 baseline's contract manifest — deliberately narrower than
services/decision_service/manifest.py: this variant has no ontology/shapes/
projections/reconciliation contracts (no RDF semantic core to version), but
DOES pin authorization/policies/identity — the THREE contract kinds spec 10's
fairness rules require to be genuinely shared ("Same authorization/policy
where applicable"). Reads contracts/manifests/deployed_version.json's SAME
"authorization"/"policies"/"identity" pointers services/decision_service
reads (services/common/contract_versions.deployed_version()) — both
variants version-pin from the exact same live file, so a contract redeploy
(`make deploy-v2`/`deploy-v3`) affects both identically, never one before
the other.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services.common.contract_versions import deployed_version
from services.decision_service.action_types import action_type_paths
from services.decision_service.manifest import content_addressed  # noqa: F401 (re-exported)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = REPO_ROOT / "contracts"
MODEL_IDS_PATH = CONTRACTS_ROOT / "manifests" / "openfga_model_ids.json"


def _sha256_of_dir(directory: Path, pattern: str) -> str:
    h = hashlib.sha256()
    if not directory.exists():
        return h.hexdigest()
    for path in sorted(directory.glob(pattern)):
        h.update(path.read_bytes())
    return h.hexdigest()


def _sha256_of_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _openfga_model_id(version: str) -> str | None:
    if not MODEL_IDS_PATH.exists():
        return None
    try:
        data = json.loads(MODEL_IDS_PATH.read_text())
    except json.JSONDecodeError:
        return None
    return data.get(version)


def build_baseline_manifest(version: dict[str, str] | None = None) -> dict[str, Any]:
    v = version or deployed_version()
    policies_dir = CONTRACTS_ROOT / "policies" / v["policies"]
    authorization_file = CONTRACTS_ROOT / "authorization" / v["authorization"] / "model.fga"
    identity_file = CONTRACTS_ROOT / "identity" / v["identity"] / "mapping_rules.yaml"

    actions: dict[str, Any] = {}
    for name, path in action_type_paths(v["actions"]).items():
        import yaml

        raw = yaml.safe_load(path.read_text())
        actions[name] = {"version": raw["version"], "sha256": _sha256_of_file(path)}

    return {
        "opa": {"version": v["policies"], "sha256": _sha256_of_dir(policies_dir, "*")},
        "openfga": {
            "version": v["authorization"],
            "sha256": _sha256_of_file(authorization_file),
            "authorization_model_id": _openfga_model_id(v["authorization"]),
        },
        "identity": {"version": v["identity"], "sha256": _sha256_of_file(identity_file)},
        "actions": actions,
        "deployed_version": v,
    }
