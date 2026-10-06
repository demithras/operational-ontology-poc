"""Interpreter for the neutral predicate/expression AST (spec/ops/*.json) against a commit-time WorldView.

Resource inputs evaluate to (Type, key) tuples. Helper reads (prose-defined in the spec) are Python functions
registered per domain (helpers_mfg.py, helpers_proj.py). Comparisons fail closed on missing / non-integer sides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .worldview import WorldView, key_of


class HelperError(Exception):
    """A prose helper cannot produce a value (maps to INVALID, zero effects)."""


@dataclass
class Ctx:
    view: WorldView
    config: dict
    link_types: dict[str, dict]
    resources: dict[str, str]  # input name -> resource type
    inputs: dict[str, Any]
    helpers: dict[str, Callable]
    holds: Callable[[str, str, str], bool]  # (type, key, relation) of the acting principal
    resources_all: tuple = ()  # every resource type name of the domain


def _isint(v: Any) -> bool:
    return type(v) is int


def ref_key(v: Any) -> Any:
    return v[1] if isinstance(v, tuple) else v


def input_value(ctx: Ctx, name: str) -> Any:
    v = ctx.inputs.get(name)
    return (ctx.resources[name], v) if name in ctx.resources and v is not None else v


def _as_keys(v: Any) -> list[str]:
    """A resource ref, a list of keys/refs, or nothing -> list of bare keys."""
    if v is None:
        return []
    if isinstance(v, tuple):
        return [v[1]]
    if isinstance(v, list):
        return [ref_key(x) for x in v]
    return [v]


def _ev_unique(n: dict, ctx: Ctx) -> Any:
    hits = set(ctx.view.keys(n["type"]))
    for c in n["where"]:
        to = ev(c["to"], ctx)
        if not isinstance(to, tuple):
            return None
        hits &= {key_of(s) for s, d in ctx.view.all_links(c["link"]) if d == f"{to[0]}:{to[1]}"}
    return (n["type"], next(iter(hits))) if len(hits) == 1 else None


def ev(n: dict, ctx: Ctx) -> Any:  # noqa: C901 - one flat dispatch over a closed vocabulary
    if "input" in n:
        return input_value(ctx, n["input"])
    if "lit" in n:
        return n["lit"]
    if "now" in n:
        return ctx.view.now
    if "field" in n:
        r = ev(n["field"][0], ctx)
        return ctx.view.field(r[0], r[1], n["field"][1]) if isinstance(r, tuple) else None
    if "unique" in n:
        return _ev_unique(n["unique"], ctx)
    if "newest" in n:
        vals = [p.get(n["newest"]["field"]) for _, p in ctx.view.items(n["newest"]["type"])]
        vals = [v for v in vals if _isint(v)]
        return max(vals) if vals else None
    if "sub" in n or "add" in n:
        vs = [ev(x, ctx) for x in n.get("sub", n.get("add"))]
        if not all(_isint(v) for v in vs):
            return None
        return vs[0] - vs[1] if "sub" in n else sum(vs)
    if "read" in n:
        return call_read(n, ctx)
    return ev_pred(n, ctx)


def call_read(n: dict, ctx: Ctx) -> Any:
    fn = ctx.helpers.get(n["read"])
    if fn is None:
        raise HelperError(f"unsupported helper {n['read']}")
    return fn(ctx, **{k: ev(v, ctx) for k, v in n.get("args", {}).items()})


def ev_pred(n: dict, ctx: Ctx) -> Any:  # noqa: C901
    k, a = n["op"], n.get("args", [])
    if k == "and":
        return all(bool(ev(x, ctx)) for x in a)
    if k == "or":
        return any(bool(ev(x, ctx)) for x in a)
    if k == "not":
        return not ev(a[0], ctx)
    if k == "actor_holds":
        r = ev(n["on"], ctx)
        return isinstance(r, tuple) and ctx.holds(r[0], r[1], n["relation"])
    if k == "any_input_prefix":
        return any(isinstance(v, str) and v.startswith(n["prefix"]) for v in ctx.inputs.values())
    if k == "all_have":
        keys = _as_keys(ev(n["of"], ctx))
        vals = [ctx.view.field(n["type"], x, n["field"]) for x in keys]
        return (bool(keys) or not n.get("nonempty")) and all(v in n["values"] for v in vals)
    if k == "any_have_link":
        src_type = ctx.link_types[n["link"]]["from_types"][0]
        return any(ctx.view.targets(n["link"], src_type, x) for x in _as_keys(ev(n["of"], ctx)))
    if k == "other_has_link_to":
        dst, exc = ev(n["dst"], ctx), ev(n["except"], ctx)
        if not isinstance(dst, tuple):
            return False
        return any(key_of(s) != ref_key(exc) for s in ctx.view.sources(n["link"], dst[0], dst[1]))
    if k == "in_read":
        return ref_key(ev(n["value"], ctx)) in _as_keys(call_read(n["read"], ctx))
    vs = [ev(x, ctx) for x in a]
    if k == "is_int":
        return _isint(vs[0])
    if k == "nonblank":
        return vs[0] is not None and str(ref_key(vs[0])).strip() != ""
    if k == "exists":
        return vs[0] is not None
    if k == "in":
        return isinstance(vs[1], (list, tuple)) and vs[0] in vs[1]
    if k == "eq":
        return vs[0] == vs[1]
    if k == "ne":
        return vs[0] != vs[1]
    if k in ("ge", "gt", "le", "lt"):
        x, y = vs
        if not (_isint(x) and _isint(y)):
            return False
        return {"ge": x >= y, "gt": x > y, "le": x <= y, "lt": x < y}[k]
    raise HelperError(f"unsupported predicate {k}")
