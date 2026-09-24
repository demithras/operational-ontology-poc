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

Phase 7 (docs/experiment/spec/07_versioning_and_replay.md item 1): extends
the Phase 5 manifest (ontology/shapes/opa/openfga/actions) with the
remaining artifact kinds the spec lists — identity mapping rules,
projection definitions, reconciliation predicates, and the decision-service
code version (the git commit was already recorded; it's now also exposed as
its own content_addressed()-able component) — and makes EVERY kind version-
aware via contracts/manifests/deployed_version.json
(services/common/contract_versions.py), so build_manifest() always reflects
whatever is CURRENTLY deployed, not a hardcoded "v1". `build_manifest(version=...)`
additionally lets replay reconstruct the manifest for an ARBITRARY archived
version (never just "current") — see services/decision_service/replay.py.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from services.common.contract_versions import deployed_version
from services.decision_service.action_types import action_type_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = REPO_ROOT / "contracts"
MANIFEST_PATH = CONTRACTS_ROOT / "manifests" / "current.json"
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


def _openfga_model_id(version: str) -> str | None:
    """The REAL OpenFGA-assigned authorization_model_id for `version`
    ("v1", "v2", ...) — distinct from the sha256 of model.fga on disk.
    OpenFGA models are immutable-by-id (07_versioning_and_replay.md item 1:
    "OpenFGA uses the historical model id... FGA models are immutable by
    id") and this store never deletes a model, so a v1 id written once
    stays valid for replay forever, even after v2/v3 are bootstrapped into
    the SAME store. Populated by services/decision_service/bootstrap_openfga.py
    and migrations/v2_to_v3/deploy.py (the only writers of new
    authorization-model versions in this experiment)."""
    if not MODEL_IDS_PATH.exists():
        return None
    try:
        data = json.loads(MODEL_IDS_PATH.read_text())
    except json.JSONDecodeError:
        return None
    return data.get(version)


def build_manifest(version: dict[str, str] | None = None) -> dict[str, Any]:
    """`version`: an explicit per-kind version-directory map (same shape as
    contracts/manifests/deployed_version.json) — e.g. what
    services/decision_service/replay.py passes to reconstruct an ARCHIVED
    manifest for a historical decision. Defaults to whatever is CURRENTLY
    deployed (the live, mutable pointer)."""
    v = version or deployed_version()

    actions: dict[str, Any] = {}
    for name, path in action_type_paths(v["actions"]).items():
        import yaml

        raw = yaml.safe_load(path.read_text())
        actions[name] = {"version": raw["version"], "sha256": _sha256_of_file(path)}

    ontology_dir = CONTRACTS_ROOT / "ontology" / v["ontology"]
    shapes_dir = CONTRACTS_ROOT / "shapes" / v["shapes"]
    policies_dir = CONTRACTS_ROOT / "policies" / v["policies"]
    authorization_file = CONTRACTS_ROOT / "authorization" / v["authorization"] / "model.fga"
    identity_file = CONTRACTS_ROOT / "identity" / v["identity"] / "mapping_rules.yaml"
    projections_dir = CONTRACTS_ROOT / "projections" / v["projections"]
    reconciliation_dir = CONTRACTS_ROOT / "reconciliation" / v["reconciliation"]

    return {
        "ontology": {"version": v["ontology"], "sha256": _sha256_of_dir(ontology_dir, "*.ttl")},
        "shapes": {"version": v["shapes"], "sha256": _sha256_of_dir(shapes_dir, "*.ttl")},
        "opa": {"version": v["policies"], "sha256": _sha256_of_dir(policies_dir, "*")},
        "openfga": {
            "version": v["authorization"],
            "sha256": _sha256_of_file(authorization_file),
            "authorization_model_id": _openfga_model_id(v["authorization"]),
        },
        "actions": actions,
        # Phase 7 additions (spec 07 item 1's full artifact list).
        "identity": {"version": v["identity"], "sha256": _sha256_of_file(identity_file)},
        "projections": {"version": v["projections"], "sha256": _sha256_of_dir(projections_dir, "*.yaml")},
        "reconciliation": {"version": v["reconciliation"], "sha256": _sha256_of_dir(reconciliation_dir, "*.yaml")},
        "code_git_commit": _git_commit(),
        "deployed_version": v,
    }


def content_addressed(component: dict[str, Any]) -> str:
    """docs/experiment/spec/05_ontology_and_contracts.md 'Policy references':
    'A decision does not merely record "policy": "inventory-policy". It
    records a content-addressed or immutable version:
    inventory-policy@sha256:...' — applied here to every *Version field
    services/decision_service/propose_flow.py stamps onto a Decision
    (ontologyVersion/shapeSetVersion/authorizationModelVersion/
    policyBundleVersion/identityMappingVersion/projectionDefinitionVersion/
    reconciliationPredicateVersion), all of which are xsd:string per
    contracts/ontology/v1/oo-core.ttl, so this format change needs no
    ontology/shape migration."""
    return f"{component['version']}@sha256:{component['sha256']}"


def write_manifest() -> dict[str, Any]:
    manifest = build_manifest()
    try:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except OSError:
        # Phase 7: services/decision_service now bind-mounts the WHOLE
        # contracts/ tree read-only (docker-compose.yml — so it can observe
        # a live contract redeploy without an image rebuild) — inside that
        # container this write is a no-op by design, never fatal to
        # startup. current.json is a host-side convenience snapshot only
        # (nothing in this repo's tests reads it); `python -m
        # services.decision_service.manifest` on the HOST still writes it
        # normally, since the host filesystem is always writable.
        pass
    return manifest


if __name__ == "__main__":
    print(json.dumps(write_manifest(), indent=2, sort_keys=True))
