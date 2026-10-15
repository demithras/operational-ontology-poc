"""Loader/validator and reference helpers for the neutral ops spec (spec/ops/<domain>.json).

Predicate vocabulary (JSON AST): expressions {input, lit, now, field:[ref,name], unique:{type,where}, newest:{type,field},
read:name+args, add, sub}; predicates {op: eq|ne|ge|gt|le|lt|in|and|or|not|is_int|nonblank|exists|actor_holds|...}.
`evaluate` implements the simple subset (enough to run preconditions and simple business rules against a world snapshot);
rules that use complex `read` helpers are defined in prose in the spec and raise Unevaluable here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]
DOMAINS = ("manufacturing", "project")


class Unevaluable(Exception):
    """The expression needs a prose-defined helper; the executor must implement it from the spec text."""


def load_ops_spec(domain: str, root: Path = ROUND3) -> dict:
    spec = json.loads((root / "spec" / "ops" / f"{domain}.json").read_text())
    validate_ops_spec(spec, root)
    return spec


def validate_ops_spec(spec: dict, root: Path = ROUND3) -> None:
    jsonschema.validate(spec, json.loads((root / "schemas" / "ops-spec.schema.json").read_text()))
    names = [o["name"] for o in spec["operations"]]
    if len(set(names)) != len(names):
        raise ValueError("duplicate operation names")
    rt = {t["name"] for t in spec["resource_types"]}
    for o in spec["operations"]:
        for i in o["inputs"]:
            if i["type"] == "resource" and i.get("resource_type") not in rt:
                raise ValueError(f"{o['name']}.{i['name']}: unknown resource type {i.get('resource_type')}")
        if not set(o["gated_inputs"]) <= {i["name"] for i in o["inputs"]}:
            raise ValueError(f"{o['name']}: gated input not among inputs")


class World:
    """Minimal in-memory view built from a world snapshot (r3_shared.world.WorldReader.snapshot()) or a spec seed."""

    def __init__(self, objects: dict[str, dict], links: list[tuple[str, str, str]], now: int = 0, actor_relations=()):
        self.objects, self.links, self.now = objects, [tuple(x) for x in links], now
        self.actor_relations = {tuple(r) for r in actor_relations}  # (type, key, relation)

    @classmethod
    def from_seed(cls, seed: dict, **kw) -> "World":
        return cls({f"{o['type']}:{o['key']}": dict(o["props"]) for o in seed["objects"]},
                   [(l["link_type"], l["src"], l["dst"]) for l in seed["links"]], **kw)

    @classmethod
    def from_snapshot(cls, snap: dict, **kw) -> "World":
        return cls({k: dict(v["props"]) for k, v in snap["objects"].items()}, [tuple(l) for l in snap["links"]], **kw)


def _resolve(spec_op: dict, name: str, args: dict) -> tuple[str, str] | Any:
    inp = next(i for i in spec_op["inputs"] if i["name"] == name)
    v = args.get(name)
    return (inp["resource_type"], v) if inp["type"] == "resource" and v is not None else v


def evaluate(node: Any, op: dict, args: dict, w: World) -> Any:
    if "input" in node:
        return _resolve(op, node["input"], args)
    if "lit" in node:
        return node["lit"]
    if "now" in node:
        return w.now
    if "field" in node:
        ref = evaluate(node["field"][0], op, args, w)
        if not isinstance(ref, tuple):
            return None
        return w.objects.get(f"{ref[0]}:{ref[1]}", {}).get(node["field"][1])
    if "unique" in node:
        u = node["unique"]
        hits = [k for k in w.objects if k.startswith(u["type"] + ":")]
        for cond in u["where"]:
            to = evaluate(cond["to"], op, args, w)
            if not isinstance(to, tuple):
                return None
            hits = [k for k in hits if (cond["link"], k, f"{to[0]}:{to[1]}") in w.links]
        return tuple(hits[0].split(":", 1)) if len(hits) == 1 else None
    if "newest" in node:
        vals = [p.get(node["newest"]["field"]) for k, p in w.objects.items() if k.startswith(node["newest"]["type"] + ":")]
        vals = [v for v in vals if isinstance(v, int)]
        return max(vals) if vals else None
    if "sub" in node or "add" in node:
        vs = [evaluate(x, op, args, w) for x in node.get("sub", node.get("add"))]
        if any(not isinstance(v, int) or isinstance(v, bool) for v in vs):
            return None
        return vs[0] - vs[1] if "sub" in node else sum(vs)
    if "read" in node:
        raise Unevaluable(node["read"])
    k = node["op"]
    a = node.get("args", [])
    if k in ("and", "or"):
        vals = [bool(evaluate(x, op, args, w)) for x in a]
        return all(vals) if k == "and" else any(vals)
    if k == "not":
        return not evaluate(a[0], op, args, w)
    if k == "actor_holds":
        ref = evaluate(node["on"], op, args, w)
        return isinstance(ref, tuple) and (ref[0], ref[1], node["relation"]) in w.actor_relations
    vs = [evaluate(x, op, args, w) for x in a]
    if k == "is_int":
        return isinstance(vs[0], int) and not isinstance(vs[0], bool)
    if k == "nonblank":
        return vs[0] is not None and str(vs[0]).strip() != ""
    if k == "exists":
        return vs[0] is not None
    if k == "in":
        return vs[0] in vs[1]
    if k == "eq":
        return vs[0] == vs[1]
    if k == "ne":
        return vs[0] != vs[1]
    if k in ("ge", "gt", "le", "lt"):
        x, y = vs
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y)):
            return False  # fail closed: a comparison with a missing/non-integer side does not hold
        return {"ge": x >= y, "gt": x > y, "le": x <= y, "lt": x < y}[k]
    raise Unevaluable(k)
