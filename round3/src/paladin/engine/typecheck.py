"""Runtime checking of values against IR type expressions (ontology/ir.schema.json typeExpr).

``resolve_ref(type_ref, value)`` is supplied by the caller (store / read view) and returns a
problem string or None; this module never decides what a reference points at.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Optional

from .canon import is_json_value

RefResolver = Callable[[str, Any], Optional[str]]


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _datetime_ok(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
        return True
    except ValueError:
        return False


def _date_ok(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


_PRIMITIVE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": _is_int,
    "number": lambda v: _is_int(v) or (isinstance(v, float) and v == v and v not in (float("inf"), float("-inf"))),
    "boolean": lambda v: isinstance(v, bool),
    "datetime": _datetime_ok,
    "date": _date_ok,
    "json": is_json_value,
    "bytes": lambda v: isinstance(v, (bytes, bytearray)),
}


def check(te: Any, v: Any, resolve_ref: RefResolver) -> Optional[str]:
    """Problem description if ``v`` does not inhabit ``te``; None when it does."""
    if isinstance(te, str):
        ok = _PRIMITIVE_CHECKS.get(te)
        if ok is None:
            return f"unknown primitive type {te!r}"
        return None if ok(v) else f"expected {te}, got {type(v).__name__}"
    if isinstance(te, dict) and len(te) == 1:
        (ctor, inner), = te.items()
        if ctor == "optional":
            return None if v is None else check(inner, v, resolve_ref)
        if ctor == "list":
            if not isinstance(v, (list, tuple)):
                return f"expected list, got {type(v).__name__}"
            for i, x in enumerate(v):
                p = check(inner, x, resolve_ref)
                if p:
                    return f"[{i}] {p}"
            return None
        if ctor == "ref":
            if not isinstance(v, (str, int)) or isinstance(v, bool):
                return f"reference to {inner!r} must be a scalar key, got {type(v).__name__}"
            return resolve_ref(inner, v)
    return f"malformed type expression {te!r}"


def ref_values(te: Any, v: Any) -> list[tuple[str, Any]]:
    """(declared ref type, key) pairs contained in a value that already type-checks."""
    if v is None:
        return []
    if isinstance(te, dict) and len(te) == 1:
        (ctor, inner), = te.items()
        if ctor == "ref":
            return [(inner, v)]
        if ctor == "optional":
            return ref_values(inner, v)
        if ctor == "list":
            out: list[tuple[str, Any]] = []
            for x in v:
                out += ref_values(inner, x)
            return out
    return []
