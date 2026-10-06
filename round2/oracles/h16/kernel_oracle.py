"""H16 oracle: what the frozen kernel is, read from the frozen schema and the preregistration, not from the Engine.

Allowed imports: stdlib and eoo_ir (the independent IR validator). Never eoo_engine / eoo_toolchain / domains logic.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_ir import validate

ROOT = Path(__file__).resolve().parents[2]


def frozen_kernel_kinds() -> list[str]:
    """Resource array fields of the frozen IR schema (the kernel kinds), sorted."""
    s = json.loads((ROOT / "ontology/ir.schema.json").read_text())
    return sorted(k for k, v in s["properties"].items() if v.get("type") == "array" and "$ref" in v.get("items", {}))


def preregistered_kernel_kinds() -> list[str]:
    return sorted(json.loads((ROOT / "protocol/ENGINE_PREREG.json").read_text())["kernel_snapshot"]["kernel_resource_kinds"])


def package_kinds_outside_kernel(pkg: dict) -> list[str]:
    """Top-level arrays of ``pkg`` that are not frozen kernel kinds (imports is a package field, not a kind)."""
    kinds = set(frozen_kernel_kinds())
    return sorted(k for k, v in pkg.items() if isinstance(v, list) and k != "imports" and k not in kinds)


def legal(pkg: dict) -> bool:
    """Schema + referential validity and only kernel kinds."""
    return not validate(pkg) and not package_kinds_outside_kernel(pkg)
