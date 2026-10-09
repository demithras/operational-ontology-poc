"""Load + strictly validate the frozen external system declarations (spec/external/<domain>.systems.json; P1f-3)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]
_PLACEHOLDER = re.compile(r"<([a-z_][a-z0-9_]*)>")
OBSERVABILITY = ("full", "effects_only", "none")
IDEMPOTENCY = ("at_most_once", "idempotent_set", "exactly_once_required")


def validate_systems(doc: dict, root: Path = ROUND3) -> dict:
    """Schema + semantics check; returns doc. ValueError/ValidationError on any violation."""
    jsonschema.validate(doc, json.loads((root / "schemas" / "external-systems.schema.json").read_text()))
    for name, sysd in doc["systems"].items():
        if sysd["observability"] == "none" and not sysd.get("generated"):
            raise ValueError(f"{name}: a `none` system must be declared generated (Q3)")
        for op, od in sysd["operations"].items():
            rest = _PLACEHOLDER.sub("", od["target_rule"])
            if "<" in rest:
                raise ValueError(f"{name}.{op}: malformed target_rule {od['target_rule']!r}")
    return doc


def load_systems(domain: str, root: Path = ROUND3) -> dict:
    return validate_systems(json.loads((root / "spec" / "external" / f"{domain}.systems.json").read_text()), root)


def observability(doc: dict, system: str) -> str:
    return doc["systems"][system]["observability"]


def idempotency(doc: dict, system: str, operation: str) -> str:
    return doc["systems"][system]["operations"][operation]["idempotency"]


def placeholders(target_rule: str) -> list[str]:
    return _PLACEHOLDER.findall(target_rule)


def render_target(target_rule: str, payload: dict) -> str:
    """Deterministic target string: <name> -> str(payload[name]). ValueError when a field is absent."""
    def sub(m):
        if m.group(1) not in payload:
            raise ValueError(f"target rule field {m.group(1)!r} missing from payload")
        return str(payload[m.group(1)])
    return _PLACEHOLDER.sub(sub, target_rule)
