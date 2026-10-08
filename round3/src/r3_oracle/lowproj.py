"""Canonical low projection (PROT-H26 s6, P1e-8). Oracle-owned: the candidate never controls it; its sha256 is frozen
in FREEZE_G3 (contract invalid_if). Pure; imports r3_shared.evidence only.

obs(call) = canonical_bytes({"m": method, "status": status, "body": body}); tool lists as sorted
[{name, input_schema}]; event lists as returned. The ONLY normalisation: values at VOLATILE_PATHS are alpha-renamed by
first appearance within the run (`Renamer`). Digests, ticks and seqs are NOT normalised.
"""
from __future__ import annotations

from typing import Any

from r3_shared.evidence import canonical_bytes

VOLATILE_PATHS = {("approve", "body.decision_id")}


class Renamer:
    """Alpha-renames volatile values by first appearance (one Renamer per run, i.e. per world)."""

    def __init__(self) -> None:
        self._m: dict[str, str] = {}

    def name(self, v: Any) -> Any:
        if not isinstance(v, str):
            return v
        return self._m.setdefault(v, f"vol-{len(self._m)}")


def project(method: str, status: str, body: dict, renamer: Renamer | None = None) -> bytes:
    body = dict(body) if isinstance(body, dict) else body
    if renamer is not None and (method, "body.decision_id") in VOLATILE_PATHS and isinstance(body, dict) \
            and "decision_id" in body:
        body["decision_id"] = renamer.name(body["decision_id"])
    return canonical_bytes({"m": method, "status": status, "body": body})


def project_result(method: str, result, renamer: Renamer | None = None) -> bytes:
    return project(method, result.status, result.body, renamer)


def project_tools(tools) -> bytes:
    rows = sorted(({"name": t.name, "input_schema": t.input_schema} for t in tools), key=lambda r: r["name"])
    return canonical_bytes({"m": "tools", "tools": rows})


def project_events(result) -> bytes:
    return project("poll", result.status, result.body)


def diff(a: list[bytes], b: list[bytes]) -> dict | None:
    """First divergence between two observation sequences, or None. A length difference is a divergence."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return {"index": i, "a": x.decode(errors="replace"), "b": y.decode(errors="replace")}
    if len(a) != len(b):
        return {"index": min(len(a), len(b)), "a": None, "b": None, "length": [len(a), len(b)]}
    return None
