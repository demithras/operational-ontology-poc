"""E-9 edge-case generators (pure data; shared by test_h27_e9_conformance.py). Each generator returns (label, payload)."""
from __future__ import annotations

import copy

WRONG = {"integer": [("str", "7"), ("float", 1.5), ("bool", True), ("list", [1]), ("dict", {"a": 1})],
         "number": [("str", "1.5"), ("bool", False), ("list", []), ("dict", {})],
         "boolean": [("int1", 1), ("int0", 0), ("str", "true"), ("list", [])],
         "string": [("int", 3), ("float", 2.5), ("bool", True), ("list", ["a"]), ("dict", {})],
         "resource": [("int", 3), ("bool", True), ("list", ["a"]), ("dict", {}), ("empty", ""), ("blank", "   ")],
         "json": []}
GOOD_VAL = {"integer": 1, "number": 1.5, "boolean": True, "string": "x", "json": {"a": [1, 2]}}


def good_args(ops: dict, op: dict) -> dict:
    keys = {}
    for o in ops["seed"]["objects"]:
        keys.setdefault(o["type"], o["key"])
    out = {}
    for i in op["inputs"]:
        if i["type"] == "resource":
            out[i["name"]] = keys.get(i["resource_type"], "K-1")
        else:
            out[i["name"]] = GOOD_VAL[i["type"]]
    return out


def op_cases(ops: dict, limit_ops=None):
    """(label, op_name, args) for call_tool/direct/approve."""
    out = []
    for op in ops["operations"][:limit_ops]:
        n, g = op["name"], good_args(ops, op)
        out.append((f"{n}:valid", n, copy.deepcopy(g)))
        out.append((f"{n}:unknown-key", n, {**g, "zz_unknown": 1}))
        out.append((f"{n}:unknown-key-null", n, {**g, "zz_unknown": None}))
        out.append((f"{n}:empty-args", n, {}))
        for bad in (None, [], "x", 5, [g]):
            out.append((f"{n}:args-not-object:{type(bad).__name__}", n, bad))
        for i in op["inputs"]:
            nm = i["name"]
            miss = {k: v for k, v in g.items() if k != nm}
            out.append((f"{n}:{nm}:missing{'-req' if i['required'] else '-opt'}", n, miss))
            out.append((f"{n}:{nm}:null{'-req' if i['required'] else '-opt'}", n, {**g, nm: None}))
            for lab, v in WRONG[i["type"]]:
                out.append((f"{n}:{nm}:{i['type']}-as-{lab}", n, {**g, nm: v}))
            if i["type"] == "json":
                for lab, v in (("str", "s"), ("list", [1]), ("zero", 0), ("false", False), ("empty-str", "")):
                    out.append((f"{n}:{nm}:json-{lab}", n, {**g, nm: v}))
            if i["type"] == "number":
                out.append((f"{n}:{nm}:number-int", n, {**g, nm: 3}))
            if i["type"] == "integer":
                out.append((f"{n}:{nm}:integer-big", n, {**g, nm: 10 ** 12}))
    out.append(("unknown-op", "no_such_op", {}))
    out.append(("op-none", None, {}))
    out.append(("op-empty", "", {}))
    return out


EDGE = {"id": "e-x", "issuer": "p", "child": "c", "parent": None,
        "scope": {"operations": ["op"], "resources": [{"type": "Part", "keys": None}]},
        "expires_at": None, "redelegable": False, "issued_at": 0}
BADV = [("int", 3), ("str", "s"), ("empty", ""), ("list", []), ("dict", {}), ("float", 1.5), ("bool", True), ("none", None)]


def edge_cases(n_ids: int = 0):
    """(label, edge) - valid controls plus every field removed / added / mistyped, scope & resource malformations."""
    out, k = [], [0]

    def add(label, e):
        k[0] += 1
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"]:
            e = {**e, "id": f"{e['id']}-{k[0]}"}
        out.append((label, e))
    add("valid", EDGE)
    add("valid-parent-str", {**EDGE, "parent": "pe"})
    add("valid-expiry", {**EDGE, "expires_at": 99, "redelegable": True})
    add("valid-keys-list", {**EDGE, "scope": {"operations": [], "resources": [{"type": "Part", "keys": ["a"]}]}})
    add("valid-empty-scope", {**EDGE, "scope": {"operations": [], "resources": []}})
    for f in EDGE:
        add(f"missing-{f}", {x: v for x, v in EDGE.items() if x != f})
        for lab, v in BADV:
            add(f"{f}={lab}", {**EDGE, f: v})
    add("extra-key", {**EDGE, "zz": 1})
    add("extra-key-null", {**EDGE, "zz": None})
    for lab in ("int", "str", "list", "none", "empty"):
        add(f"edge-not-object-{lab}", {"int": 3, "str": "e", "list": [EDGE], "none": None, "empty": {}}[lab])
    sc = EDGE["scope"]
    for f in ("operations", "resources"):
        add(f"scope-missing-{f}", {**EDGE, "scope": {x: v for x, v in sc.items() if x != f}})
        for lab, v in BADV + [("list-int", [1]), ("list-none", [None])]:
            add(f"scope.{f}={lab}", {**EDGE, "scope": {**sc, f: v}})
    add("scope-extra", {**EDGE, "scope": {**sc, "zz": 1}})
    add("ops-with-int", {**EDGE, "scope": {"operations": ["a", 1], "resources": []}})
    for r_lab, r in [("not-object", "x"), ("missing-keys", {"type": "Part"}), ("missing-type", {"keys": None}),
                     ("extra", {"type": "Part", "keys": None, "zz": 1}), ("type-int", {"type": 3, "keys": None}),
                     ("keys-str", {"type": "Part", "keys": "a"}), ("keys-int-item", {"type": "Part", "keys": [1]}),
                     ("keys-empty-ok", {"type": "Part", "keys": []}), ("keys-none-item", {"type": "Part", "keys": [None]}),
                     ("none", None), ("list", [])]:
        add(f"resource-{r_lab}", {**EDGE, "scope": {"operations": [], "resources": [r]}})
    for lab, v in (("zero", 0), ("big", 10 ** 9), ("neg", -1)):
        add(f"issued_at-{lab}", {**EDGE, "issued_at": v})
        add(f"expires_at-{lab}", {**EDGE, "expires_at": v})
    for j in range(max(0, n_ids)):
        add(f"valid-variant-{j}", {**EDGE, "child": f"c{j}", "scope": {"operations": [f"o{j}"], "resources": []}})
    return out


def revoke_cases():
    vals = [("str", "e-unknown"), ("str2", "x"), ("long", "e" * 200), ("space", " "), ("spaces", "   "), ("tab", "\t"),
            ("newline", "\n"), ("unicode", "ключ-é"), ("digits", "123"), ("empty", ""), ("none", None), ("int", 3),
            ("zero", 0), ("float", 1.5), ("true", True), ("false", False), ("list", ["e"]), ("empty-list", []),
            ("dict", {"id": "e"}), ("empty-dict", {}), ("bytes", b"e"), ("tuple", ("e",))]
    out = list(vals)
    out += [(f"id-{i}", f"edge-{i}") for i in range(100)]
    out += [(f"int-{i}", i) for i in range(1, 80)]
    out += [(f"list-{i}", [f"e{i}"]) for i in range(10)]
    return out
