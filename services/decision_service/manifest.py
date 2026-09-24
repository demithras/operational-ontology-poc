"""contracts/manifests/current.json generator — docs/experiment/spec/13_repository_contract.md
"Contract manifest" / docs/experiment/spec/05_ontology_and_contracts.md
"A decision ... records a content-addressed or immutable version ... for
every deployed artifact".

Every sha256 here is computed over RAW BYTES straight off disk at call time
(never hand-typed/cached), matching the existing convention in
services/projection_builder/writer.py's projection_definition_sha256 — so a
manifest can never drift from the files it claims to describe. Called at
services/decision_service app startup (idempotent — always overwrites
contracts/manifests/current.json with the current on-disk truth) and
importable directly by services/decision_service/policy.py etc. for the
individual hashes they need to persist per-decision.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from services.common.contract_versions import ONTOLOGY_CONTRACT_VERSION
from services.decision_service.action_types import action_type_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "contracts" / "manifests" / "current.json"

ONTOLOGY_DIR = REPO_ROOT / "contracts" / "ontology" / "v1"
SHAPES_DIR = REPO_ROOT / "contracts" / "shapes" / "v1"
POLICIES_DIR = REPO_ROOT / "contracts" / "policies" / "v1"
AUTHORIZATION_MODEL_FILE = REPO_ROOT / "contracts" / "authorization" / "v1" / "model.fga"

SHAPE_SET_VERSION = "v1"
AUTHORIZATION_MODEL_VERSION = "v1"
POLICY_BUNDLE_VERSION = "v1"


def _sha256_of_dir(directory: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for path in sorted(directory.glob(pattern)):
        h.update(path.read_bytes())
    return h.hexdigest()


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def build_manifest() -> dict[str, Any]:
    actions: dict[str, Any] = {}
    for name, path in action_type_paths().items():
        import yaml

        raw = yaml.safe_load(path.read_text())
        actions[name] = {"version": raw["version"], "sha256": _sha256_of_file(path)}

    return {
        "ontology": {"version": ONTOLOGY_CONTRACT_VERSION, "sha256": _sha256_of_dir(ONTOLOGY_DIR, "*.ttl")},
        "shapes": {"version": SHAPE_SET_VERSION, "sha256": _sha256_of_dir(SHAPES_DIR, "*.ttl")},
        "opa": {"version": POLICY_BUNDLE_VERSION, "sha256": _sha256_of_dir(POLICIES_DIR, "*")},
        "openfga": {
            "version": AUTHORIZATION_MODEL_VERSION,
            "sha256": _sha256_of_file(AUTHORIZATION_MODEL_FILE),
        },
        "actions": actions,
        "code_git_commit": _git_commit(),
    }


def content_addressed(component: dict[str, Any]) -> str:
    """docs/experiment/spec/05_ontology_and_contracts.md 'Policy references':
    'A decision does not merely record "policy": "inventory-policy". It
    records a content-addressed or immutable version:
    inventory-policy@sha256:...' — applied here to every *Version field
    services/decision_service/propose_flow.py stamps onto a Decision
    (ontologyVersion/shapeSetVersion/authorizationModelVersion/
    policyBundleVersion), all of which are xsd:string per
    contracts/ontology/v1/oo-core.ttl, so this format change needs no
    ontology/shape migration."""
    return f"{component['version']}@sha256:{component['sha256']}"


def write_manifest() -> dict[str, Any]:
    manifest = build_manifest()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(write_manifest(), indent=2, sort_keys=True))
