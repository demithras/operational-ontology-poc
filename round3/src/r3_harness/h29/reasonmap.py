"""spec/gate5/reason-map.json loader (G5-E22). Form: {"form": "r3-reason-map-1", "variants": {<variant>: {<raw INVALID reason>: <one of
INPUT_INVALID_REASONS>}}}. The real file is built by the equivalence auditor; this module only validates and reads it. No free-text matching:
a raw reason is mapped by exact key, an unmapped raw reason stays raw and so fails the INPUT_INVALID membership (G5-E14)."""
from __future__ import annotations

import json
from pathlib import Path

from r3_shared.recovery import INPUT_INVALID_REASONS

FORM = "r3-reason-map-1"
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "spec" / "gate5" / "reason-map.json"
SCHEMA = {"type": "object", "required": ["form", "variants"], "additionalProperties": False,
          "properties": {"form": {"const": FORM},
                         "variants": {"type": "object", "additionalProperties": {
                             "type": "object", "additionalProperties": {"enum": list(INPUT_INVALID_REASONS)}}}}}


class ReasonMapError(ValueError):
    pass


def validate(doc) -> dict:
    """-> {variant: {raw: class}}. ReasonMapError on any deviation from SCHEMA."""
    if not isinstance(doc, dict) or set(doc) != {"form", "variants"}:
        raise ReasonMapError("reason map: top level must be exactly {form, variants}")
    if doc["form"] != FORM:
        raise ReasonMapError(f"reason map: form {doc['form']!r} != {FORM!r}")
    if not isinstance(doc["variants"], dict) or not doc["variants"]:
        raise ReasonMapError("reason map: variants must be a non-empty object")
    for v, m in doc["variants"].items():
        if not isinstance(m, dict):
            raise ReasonMapError(f"reason map: variant {v!r} must map raw reason -> class")
        for raw, cls in m.items():
            if not isinstance(raw, str) or cls not in INPUT_INVALID_REASONS:
                raise ReasonMapError(f"reason map: {v!r}: {raw!r} -> {cls!r} is not one of {INPUT_INVALID_REASONS}")
    return doc["variants"]


def load(path: Path | str | None = None) -> dict | None:
    """The validated per-variant tables, or None when the file does not exist (dev only: the auditor's file is a freeze-manifest entry)."""
    p = Path(path) if path else DEFAULT_PATH
    return validate(json.loads(p.read_text())) if p.is_file() else None


REAL_VARIANTS = ("paladin", "conventional")


def for_variant(variant: str, path: Path | str | None = None) -> dict:
    """The table of `variant`. {} when the file is absent or for a fake (any name that is neither registered nor in the file); a REAL variant
    missing from a present file raises (its INVALID replies could not be judged)."""
    tables = load(path)
    if tables is None:
        return {}
    if variant in tables:
        return dict(tables[variant])
    if variant in REAL_VARIANTS:
        raise ReasonMapError(f"reason map has no table for variant {variant!r}")
    return {}
