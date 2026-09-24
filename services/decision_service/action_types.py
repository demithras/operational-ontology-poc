"""Loads and validates contracts/actions/v1/*.yaml (the ActionType contract,
docs/experiment/spec/05_ontology_and_contracts.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIONS_DIR = REPO_ROOT / "contracts" / "actions" / "v1"


@dataclass(frozen=True)
class ActionType:
    name: str
    version: int
    raw: dict[str, Any]

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


_REGISTRY: dict[str, ActionType] = {}


def _load_all() -> dict[str, ActionType]:
    global _REGISTRY
    if _REGISTRY:
        return _REGISTRY
    registry: dict[str, ActionType] = {}
    for path in sorted(ACTIONS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        name = raw["name"]
        registry[name] = ActionType(name=name, version=int(raw["version"]), raw=raw)
    _REGISTRY = registry
    return registry


def get_action_type(name: str) -> ActionType | None:
    return _load_all().get(name)


def action_type_paths() -> dict[str, Path]:
    return {p.stem: p for p in sorted(ACTIONS_DIR.glob("*.yaml"))}
