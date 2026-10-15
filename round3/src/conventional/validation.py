"""Strict request validation shared by every generated request model.

Rules: unknown fields rejected; required fields must be present and non-null; integers exclude bool;
resource references are non-blank strings (the resource key); json values must be JSON-serialisable.
Validated values are deep-copied through JSON so the caller never keeps a reference into bound state.
"""
from __future__ import annotations

import json
from typing import Any


class RequestInvalid(Exception):
    """Schema violation (maps to INVALID, zero effects)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


def _check(name: str, kind: str, v: Any) -> Any:
    if kind == "integer":
        if type(v) is not int:
            raise RequestInvalid("bad_type", f"{name} must be an integer")
        return v
    if kind == "resource":
        if not isinstance(v, str) or not v.strip():
            raise RequestInvalid("bad_type", f"{name} must be a non-blank resource key")
        return v
    if kind == "string":
        if not isinstance(v, str):
            raise RequestInvalid("bad_type", f"{name} must be a string")
        return v
    if kind == "json":
        try:
            return json.loads(json.dumps(v, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise RequestInvalid("bad_type", f"{name} must be JSON") from exc
    raise RequestInvalid("bad_schema", f"unknown input kind {kind}")


def validate_inputs(schema: tuple[tuple[str, str, bool], ...], args: Any) -> dict[str, Any]:
    """schema = ((name, kind, required), ...). Returns a fresh dict containing only validated, present inputs."""
    if not isinstance(args, dict):
        raise RequestInvalid("bad_args", "args must be an object")
    names = {n for n, _, _ in schema}
    snapshot = {}
    for k in list(args):  # single read of every key: a caller-supplied mapping cannot change under us
        if not isinstance(k, str):
            raise RequestInvalid("bad_args", "field names must be strings")
        snapshot[k] = args[k]
    unknown = sorted(set(snapshot) - names)
    if unknown:
        raise RequestInvalid("unknown_field", ", ".join(unknown))
    out: dict[str, Any] = {}
    for name, kind, required in schema:
        v = snapshot.get(name)
        if v is None:
            if required:
                raise RequestInvalid("missing_field", name)
            continue
        out[name] = _check(name, kind, v)
    return out
