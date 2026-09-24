"""Loads and validates contracts/actions/<version>/*.yaml (the ActionType
contract, docs/experiment/spec/05_ontology_and_contracts.md).

Phase 7 (docs/experiment/spec/07_versioning_and_replay.md): action schemas
are versioned directories (v1, v2, ...), never rewritten in place once
published — contracts/actions/v1/transfer_inventory.yaml stays exactly what
every V1 decision pinned forever; contracts/actions/v2/transfer_inventory.yaml
is a SEPARATE, immutable file. `get_action_type(name, version)` loads from a
SPECIFIC version directory (registry cache keyed by version, so an already-
loaded v1 ActionType is never invalidated by a later v2 load); callers that
don't care about versioning (nothing in this codebase before Phase 7)
default to "v1", preserving every Phase 1-6 call site's behavior exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIONS_ROOT = REPO_ROOT / "contracts" / "actions"

# Backward-compatible constant — every pre-Phase-7 caller (services/action_worker/
# activities.py's F34 re-hash, tests) imports this name directly and always
# meant "the v1 directory". Phase 7 callers that need a SPECIFIC version use
# `actions_dir(version)` instead.
ACTIONS_DIR = ACTIONS_ROOT / "v1"


def actions_dir(version: str = "v1") -> Path:
    return ACTIONS_ROOT / version


@dataclass(frozen=True)
class ActionType:
    name: str
    version: int
    raw: dict[str, Any]
    # Phase 7: the CONTRACT version directory ("v1"/"v2"/...) this
    # ActionType was loaded from — distinct from `version` (an integer the
    # YAML itself declares, e.g. `version: 2`, and part of the hash-covered
    # decision_content_hash payload). replay uses this to find the exact
    # archived file back on disk.
    version_dir: str = "v1"

    @property
    def parameters(self) -> dict[str, Any]:
        return self.raw.get("parameters", {})

    @property
    def required_parameters(self) -> list[str]:
        """Parameter names that must be present in the propose request.
        Phase 6 step 0: a parameter spec may set `required: false` (e.g.
        transfer_inventory's `work_order`) — defaults to required=True for
        every parameter that doesn't say otherwise, preserving Phase 5
        behavior exactly."""
        return [name for name, spec in self.parameters.items() if spec.get("required", True)]

    @property
    def authorization_relation(self) -> str:
        return self.raw["authorization"]["relation"]

    @property
    def authorization_object_binding(self) -> str:
        return self.raw["authorization"]["object_binding"]

    @property
    def approval_relation(self) -> str:
        return self.raw["authorization"]["approval_relation"]

    @property
    def protected_relation(self) -> str | None:
        """Phase 6 step 0 (docs/adr/0003-protected-high-priority-transfer-authorization.md):
        an OpenFGA relation checked, in ADDITION to `authorization_relation`,
        against the same resolved object, only when evidence marks the
        proposal's linked work order HIGH priority. None for ActionTypes
        that declare no such extra protection (expedite_purchase_order,
        reschedule_work_order)."""
        return self.raw["authorization"].get("protected_relation")

    @property
    def policy_package(self) -> str:
        return self.raw["policy"]["package"]

    @property
    def policy_config(self) -> dict[str, Any]:
        return {k: v for k, v in self.raw["policy"].items() if k != "package"}

    @property
    def evidence_requirements(self) -> list[str]:
        return list(self.raw.get("evidence_requirements", []))

    @property
    def closure_required(self) -> list[str]:
        return list(self.raw.get("closure", {}).get("required", []))

    @property
    def max_evidence_freshness_s(self) -> float:
        return float(self.raw.get("closure", {}).get("max_evidence_freshness_s", 5))

    @property
    def compensation_mode(self) -> str:
        return self.raw.get("compensation", {}).get("mode", "manual_recovery_required")


_REGISTRY: dict[str, dict[str, ActionType]] = {}


def _load_all(version: str = "v1") -> dict[str, ActionType]:
    global _REGISTRY
    if version in _REGISTRY:
        return _REGISTRY[version]
    registry: dict[str, ActionType] = {}
    for path in sorted(actions_dir(version).glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        name = raw["name"]
        registry[name] = ActionType(name=name, version=int(raw["version"]), raw=raw, version_dir=version)
    _REGISTRY[version] = registry
    return registry


def get_action_type(name: str, version: str = "v1") -> ActionType | None:
    return _load_all(version).get(name)


def action_type_paths(version: str = "v1") -> dict[str, Path]:
    return {p.stem: p for p in sorted(actions_dir(version).glob("*.yaml"))}
