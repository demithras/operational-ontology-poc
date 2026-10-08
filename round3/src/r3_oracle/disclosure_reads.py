"""Oracle: expected answers of the low read channels (PROT-H26 s3), tools exposure (s3.4), canaries (s7 R26-3).
All answers are (status, body) pairs in the frozen P1e-5 forms."""
from __future__ import annotations

import json
import re

from r3_shared.disclosure import tool_schema

from . import authority, scope_v2
from .expr import Ctx, ev
from .helpers import REGISTRY
from .view import HelperError, View


def expected_read_object(lv, ref: str) -> tuple[str, dict]:
    if ref in lv.objects:
        return "OK", {"ref": ref, "props": lv.objects[ref]}
    return "INVALID", {"reason": "not_found"}


def expected_list_objects(lv, type_: str) -> tuple[str, dict]:
    if type_ not in {t["name"] for t in lv.ops_spec["resource_types"]}:
        return "INVALID", {"reason": "unknown_type"}
    return "OK", {"refs": sorted(r for r in lv.objects if r.split(":", 1)[0] == type_)}


def expected_list_links(lv, ref: str, link_type: str) -> tuple[str, dict]:
    if ref not in lv.objects:
        return "OK", {"out": [], "in": []}
    return "OK", {"out": sorted(b for (lt, a, b) in lv.links if lt == link_type and a == ref),
                  "in": sorted(a for (lt, a, b) in lv.links if lt == link_type and b == ref)}


def _jsonable(x):
    if isinstance(x, tuple) and len(x) == 2 and all(isinstance(s, str) for s in x):
        return f"{x[0]}:{x[1]}"
    if isinstance(x, (list, tuple, set, frozenset)):
        return [_jsonable(y) for y in (sorted(x) if isinstance(x, (set, frozenset)) else x)]
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    return x


def expected_query(lv, name: str, args: dict):
    """(status, body) over the LOW view as the world (s3.3); None when the oracle has no frozen answer (unknown name,
    ill-formed args): such calls are only twin-compared by the harness, never counted as read mismatches."""
    rd = next((r for r in lv.ops_spec["reads"] if r["name"] == name), None)
    if rd is None or not isinstance(args, dict):
        return None
    kw = {}
    for i in rd["inputs"]:
        v = args.get(i["name"])
        if v is None and i.get("required"):
            return None
        if i["type"] == "resource":
            if not isinstance(v, str) or ":" not in v:
                return None
            t, k = v.split(":", 1)
            v = (t, k)
        kw[i["name"]] = v
    view = View(lv.snapshot())
    try:
        if "expr" in rd:
            val = ev(rd["expr"], Ctx(rd, kw, view))
        elif name in REGISTRY:
            val = REGISTRY[name](view, **kw)
        else:
            return None
    except (HelperError, KeyError, TypeError, ValueError):
        return None
    return "OK", {"value": json.loads(json.dumps(_jsonable(val), sort_keys=True))}


def expected_tool_names(auth: dict, ops_spec: dict, observer: str, edges=()) -> set[str]:
    """s3.4 upper bound: operations the subject (or its delegators/edges) could be granted on some resource."""
    out = set()
    for op in ops_spec["operations"]:
        n = op["name"]
        if authority.could_ever_allow(observer, n, auth):
            out.add(n)
        elif any(e["child"] == observer and any(authority._op_match(p, n) or p == n for p in e["scope"]["operations"])
                 and authority.could_ever_allow(e["issuer"], n, auth) for e in edges):
            out.add(n)
    return out


def expected_tools(auth: dict, ops_spec: dict, observer: str, edges=()) -> list[dict]:
    names = expected_tool_names(auth, ops_spec, observer, edges)
    return sorted(({"name": o["name"], "input_schema": tool_schema(o)} for o in ops_spec["operations"]
                   if o["name"] in names), key=lambda r: r["name"])


# ---- canaries (s7) ---------------------------------------------------------------------------------------------
CANARY_STR = re.compile(r"c[vk]-[0-9a-f]{8,12}")
CANARY_INT_MIN = 7_000_000


def canaries_of(x) -> set:
    """Canary strings ("cv-<hex12>" values, "ck-<hex8>" keys) and ints >= 7_000_000 found anywhere in a JSON-able value."""
    out: set = set()

    def walk(v):
        if isinstance(v, dict):
            for k, y in v.items():
                walk(k)
                walk(y)
        elif isinstance(v, (list, tuple, set)):
            for y in v:
                walk(y)
        elif isinstance(v, bool):
            return
        elif isinstance(v, int):
            if v >= CANARY_INT_MIN:
                out.add(v)
        elif isinstance(v, str):
            out.update(CANARY_STR.findall(v))
    walk(x)
    return out


def scan_hits(body, protected: set) -> list:
    """Canaries in `body` that are in `protected` (the canaries of facts OUTSIDE the caller's low view)."""
    return sorted(canaries_of(body) & protected, key=str)


_ = scope_v2
