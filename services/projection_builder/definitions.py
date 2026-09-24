"""Loads contracts/projections/<version>/*.yaml — the versioned/hashed
definition each hot-projection row must cite (docs/experiment/spec/04_architecture.md
"Every projection row must include ... projection version").

sha256 is computed over the RAW FILE BYTES at load time, never hardcoded —
so it can never drift out of sync with the file on disk (the honesty rule
in docs/experiment/briefs/common.md: never fake a value that could instead
be computed).

Phase 7 (docs/experiment/spec/07_versioning_and_replay.md): `<version>` is
resolved fresh on every load_definition() call from
contracts/manifests/deployed_version.json's "projections" key
(services/common/contract_versions.py) — never cached — so a migration that
flips this pointer (e.g. v1 -> v2, when the V1->V2 ontology evolution
requires a projection-definition change too — see migrations/v1_to_v2/)
takes effect the moment services/projection_builder's next poll cycle
reloads definitions, no restart required. Defaults to "v1", matching every
Phase 4-6 caller's existing behavior exactly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from services.common.contract_versions import deployed_version

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTIONS_ROOT = REPO_ROOT / "contracts" / "projections"

PROJECTION_NAMES = (
    "work_order_risk",
    "transfer_candidates",
    "current_inventory",
    "action_eligibility_summary",
)


@dataclass(frozen=True)
class ProjectionDefinition:
    name: str
    version: str
    sha256: str
    queries: dict[str, str]


def definitions_dir() -> Path:
    return PROJECTIONS_ROOT / deployed_version()["projections"]


def load_definition(name: str) -> ProjectionDefinition:
    path = definitions_dir() / f"{name}.yaml"
    raw_bytes = path.read_bytes()
    doc = yaml.safe_load(raw_bytes.decode("utf-8"))
    if doc.get("name") != name:
        raise ValueError(f"{path}: 'name' field {doc.get('name')!r} does not match file name {name!r}")
    return ProjectionDefinition(
        name=name,
        version=str(doc["version"]),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        queries=dict(doc.get("queries") or {}),
    )


def load_all_definitions() -> dict[str, ProjectionDefinition]:
    return {name: load_definition(name) for name in PROJECTION_NAMES}
