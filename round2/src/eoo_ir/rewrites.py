"""Semantics-preserving rewrites: reordering and explicit default expansion ONLY."""
from __future__ import annotations

import copy
import random

from hypothesis import strategies as st

from .kinds import RESOURCE_ARRAYS

# (container path inside a resource kind) -> keys of set-valued string lists
_SET_LISTS = {
    "object_types": ["implements"],
    "interfaces": ["required_links", "capabilities"],
    "functions": ["reads"],
    "actions": ["authority_refs", "policy_refs", "preconditions"],
}


def _shuffle(lst: list, r: random.Random) -> None:
    r.shuffle(lst)


def _props(res: dict, r: random.Random, expand: bool) -> None:
    for key in ("properties", "required_properties"):
        lst = res.get(key)
        if isinstance(lst, list):
            _shuffle(lst, r)
            for p in lst:
                if expand and r.random() < 0.7:
                    p.setdefault("immutable", False)
                    p.setdefault("constraints", [])
                if isinstance(p.get("constraints"), list):
                    _shuffle(p["constraints"], r)


def _shuffle_keys(x, r: random.Random):
    if isinstance(x, dict):
        items = list(x.items())
        r.shuffle(items)
        return {k: _shuffle_keys(v, r) for k, v in items}
    if isinstance(x, list):
        return [_shuffle_keys(v, r) for v in x]
    return x


def rewrite(pkg: dict, seed: int) -> dict:
    r = random.Random(seed)
    p = copy.deepcopy(pkg)
    expand = r.random() < 0.8
    if expand and r.random() < 0.7:
        p.setdefault("imports", [])
    if isinstance(p.get("imports"), list):
        _shuffle(p["imports"], r)
    for kind in RESOURCE_ARRAYS:
        _shuffle(p[kind], r)
        for res in p[kind]:
            for key in _SET_LISTS.get(kind, []):
                _shuffle(res[key], r)
            _props(res, r, expand)
            if kind == "link_types" and expand and r.random() < 0.7:
                res.setdefault("directed", True)
                res.setdefault("properties", [])
            if kind == "authority_rules" and expand and r.random() < 0.7:
                res.setdefault("delegation_allowed", False)
            if kind in ("functions", "actions") and expand:
                for q in res["inputs"]:  # input ORDER is significant: only defaults expand
                    if r.random() < 0.7:
                        q.setdefault("required", True)
            if kind == "actions":
                for e in res["effects"]:
                    if isinstance(e.get("fields"), list):
                        _shuffle(e["fields"], r)
    return _shuffle_keys(p, r)


def allowed_rewrite(pkg: dict) -> st.SearchStrategy[dict]:
    """Strategy for a package that is semantically identical to ``pkg`` but reordered/default-expanded."""
    return st.integers(0, 2**31).map(lambda s: rewrite(pkg, s))
