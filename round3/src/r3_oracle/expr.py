"""Independent evaluator of the ops-spec JSON predicate/expression AST (spec/ops/<domain>.json).

Complete for every node kind used by the two domains (including the prose-defined `read` helpers, resolved through
helpers.REGISTRY). Fails closed: comparisons with a missing or non-integer side are False.
"""
from __future__ import annotations

from typing import Any

from .helpers import REGISTRY
from .view import HelperError, Ref, View, rid

EPHEMERAL_SKIP = ("json",)


class Ctx:
    def __init__(self, op: dict, args: dict, view: View):
        self.op, self.args, self.v = op, args, view
        self.by_name = {i["name"]: i for i in op["inputs"]}


def _isint(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _input(c: Ctx, name: str):
    spec = c.by_name[name]
    val = c.args.get(name)
    if spec["type"] == "resource":
        return (spec["resource_type"], val) if isinstance(val, str) and val != "" else None
    return val


def _key(x):
    return x[1] if isinstance(x, tuple) else x


def _refs(x, type_: str | None = None) -> list[Ref]:
    if x is None:
        return []
    if isinstance(x, tuple):
        return [x]
    return [e if isinstance(e, tuple) else (type_ or "Hypothesis", e) for e in x]


def call_read(c: Ctx, node: dict) -> Any:
    fn = REGISTRY.get(node["read"])
    if fn is None:
        raise HelperError(f"no helper {node['read']}")
    kw = {k: ev(a, c) for k, a in (node.get("args") or {}).items()}
    for k, val in list(kw.items()):  # key arguments like claim/part may arrive as Refs; helpers take what they need
        kw[k] = val
    return fn(c.v, **kw)


def ev(n: dict, c: Ctx) -> Any:  # noqa: C901 - one branch per AST node kind
    v = c.v
    if "input" in n:
        return _input(c, n["input"])
    if "lit" in n:
        return n["lit"]
    if "now" in n:
        return v.now
    if "field" in n and "op" not in n:
        base = ev(n["field"][0], c)
        return v.field(base, n["field"][1]) if isinstance(base, tuple) else None
    if "unique" in n:
        u = n["unique"]
        hits = v.refs_of(u["type"])
        for cond in u["where"]:
            to = ev(cond["to"], c)
            if not isinstance(to, tuple):
                return None
            hits = [h for h in hits if v.has_link(cond["link"], h, to)]
        return hits[0] if len(hits) == 1 else None
    if "newest" in n:
        vals = [v.field(r, n["newest"]["field"]) for r in v.refs_of(n["newest"]["type"])]
        vals = [x for x in vals if _isint(x)]
        return max(vals) if vals else None
    if "sub" in n or "add" in n:
        xs = [ev(x, c) for x in n.get("sub", n.get("add"))]
        if not all(_isint(x) for x in xs):
            return None
        return xs[0] - xs[1] if "sub" in n else sum(xs)
    if "read" in n and "op" not in n:
        return call_read(c, n)
    k, a = n["op"], n.get("args", [])
    if k == "and":
        return all(bool(ev(x, c)) for x in a)
    if k == "or":
        return any(bool(ev(x, c)) for x in a)
    if k == "not":
        return not ev(a[0], c)
    if k == "actor_holds":
        ref = ev(n["on"], c)
        return isinstance(ref, tuple) and (ref[0], ref[1], n["relation"]) in v.relations
    if k == "any_input_prefix":
        return any(isinstance(val, str) and val.startswith(n["prefix"]) for val in c.args.values())
    if k == "any_have_link":
        return any(any(True for _ in v.out(n["link"], r)) for r in _refs(ev(n["of"], c)))
    if k == "all_have":
        items = _refs(ev(n["of"], c), n["type"])
        if n.get("nonempty") and not items:
            return False
        return all(v.field(r, n["field"]) in n["values"] for r in items)
    if k == "other_has_link_to":
        dst, exc = ev(n["dst"], c), ev(n["except"], c)
        return isinstance(dst, tuple) and any(s != exc for s in v.inc(n["link"], dst))
    if k == "in_read":
        return _key(ev(n["value"], c)) in [_key(x) for x in (ev(n["read"], c) or [])]
    if k == "exists":
        node = a[0]
        val = ev(node, c)
        if "read" in node and node["read"] == "new_experiment_id":
            return val is not None and v.exists(("Experiment", val))
        if isinstance(val, tuple):
            return v.exists(val)
        return val is not None
    xs = [ev(x, c) for x in a]
    if k == "is_int":
        return _isint(xs[0])
    if k == "nonblank":
        return xs[0] is not None and str(xs[0]).strip() != ""
    if k == "in":
        coll = xs[1]
        return xs[0] is not None and any(xs[0] == e or _key(xs[0]) == e for e in coll)
    if k == "eq":
        return xs[0] == xs[1]
    if k == "ne":
        return xs[0] != xs[1]
    if k in ("ge", "gt", "le", "lt"):
        if not all(_isint(x) for x in xs):
            return False
        x, y = xs
        return {"ge": x >= y, "gt": x > y, "le": x <= y, "lt": x < y}[k]
    raise HelperError(f"unknown AST op {k}")


__all__ = ["Ctx", "ev", "rid"]
