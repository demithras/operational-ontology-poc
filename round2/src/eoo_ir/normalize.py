"""The ONLY normalizations semantic-equivalence.md allows.

Allowed: sort resource arrays by id; sort set-valued lists (duplicates KEPT); sort property
arrays by name; expand schema defaults explicitly; canonicalize object keys.

Forbidden (and not done here): inferring cardinality/kind/authority/version/flags, filling a
missing optional field (absent stays absent; null is not absent), merging duplicates,
reordering order-significant lists (function/action inputs, action effects), turning
Function into Action or back, collapsing 1 / 1.0 / true, rewriting any string.

The function is defensive: it never raises on schema-invalid input, it just leaves unknown
shapes untouched, so ``equivalent`` is defined for any JSON-like value.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from .kinds import RESOURCE_ARRAYS


def jkey(x: Any) -> str:
    """Canonical JSON text; distinguishes true/1/1.0 and key order never matters."""
    return json.dumps(x, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=True)


def _sorted_values(lst: list) -> list:
    if all(isinstance(v, str) for v in lst):
        return sorted(lst)
    return sorted(lst, key=jkey)


def _sort_set(d: dict, key: str) -> None:
    if isinstance(d.get(key), list):
        d[key] = _sorted_values(d[key])


def _default(d: dict, key: str, value: Any) -> None:
    if key not in d:
        d[key] = copy.deepcopy(value)


def _property(p: Any) -> Any:
    if not isinstance(p, dict):
        return p
    _default(p, "immutable", False)
    _default(p, "constraints", [])
    _sort_set(p, "constraints")
    return p


def _properties(d: dict, key: str) -> None:
    v = d.get(key)
    if isinstance(v, list):
        items = [_property(p) for p in v]
        d[key] = sorted(items, key=lambda p: (p.get("name") if isinstance(p, dict) and isinstance(p.get("name"), str) else "", jkey(p)))


def _parameters(d: dict, key: str) -> None:
    v = d.get(key)
    if isinstance(v, list):
        for p in v:
            if isinstance(p, dict):
                _default(p, "required", True)  # order of inputs is significant: NOT sorted


def _object_type(o: dict) -> None:
    _properties(o, "properties")
    _sort_set(o, "implements")


def _link_type(lk: dict) -> None:
    _default(lk, "directed", True)
    _default(lk, "properties", [])
    _properties(lk, "properties")


def _interface(i: dict) -> None:
    _properties(i, "required_properties")
    _sort_set(i, "required_links")
    _sort_set(i, "capabilities")


def _function(f: dict) -> None:
    _parameters(f, "inputs")
    _sort_set(f, "reads")


def _action(a: dict) -> None:
    _parameters(a, "inputs")
    for key in ("authority_refs", "policy_refs", "preconditions"):
        _sort_set(a, key)
    if isinstance(a.get("effects"), list):  # effect order is significant
        for e in a["effects"]:
            if isinstance(e, dict):
                _sort_set(e, "fields")


def _authority_rule(r: dict) -> None:
    _default(r, "delegation_allowed", False)


def _observation_type(o: dict) -> None:
    _properties(o, "properties")


_PER_KIND = {
    "object_types": _object_type,
    "link_types": _link_type,
    "interfaces": _interface,
    "functions": _function,
    "actions": _action,
    "authority_rules": _authority_rule,
    "observation_types": _observation_type,
}


def _canon_keys(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _canon_keys(x[k]) for k in sorted(x, key=lambda k: (str(type(k)), str(k)))}
    if isinstance(x, list):
        return [_canon_keys(v) for v in x]
    return x


def normalize(pkg: Any) -> Any:
    """Return the fully normalized copy of ``pkg`` (the input is never mutated)."""
    if not isinstance(pkg, dict):
        return copy.deepcopy(pkg)
    out = copy.deepcopy(pkg)
    _default(out, "imports", [])
    _sort_set(out, "imports")
    for kind in RESOURCE_ARRAYS:
        arr = out.get(kind)
        if not isinstance(arr, list):
            continue
        fn = _PER_KIND.get(kind)
        for r in arr:
            if fn is not None and isinstance(r, dict):
                fn(r)
        out[kind] = sorted(arr, key=lambda r: (r.get("id") if isinstance(r, dict) and isinstance(r.get("id"), str) else "", jkey(r)))
    return _canon_keys(out)
