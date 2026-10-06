"""Type / cardinality / Function-vs-Action conformance of a generated SDK against the independent IR type checker."""
from __future__ import annotations

import dataclasses
from collections import Counter

from eoo_toolchain.runtime import ActionRequest, FunctionCall, Obj

from .differential import load_oracle_module


class _Rec:
    """Recording client: which navigation call does an accessor make, with what arguments."""

    def __init__(self):
        self.calls = []

    def follow(self, lt, t, key, direction="out"):
        self.calls.append(("follow", lt, t, direction))
        return []

    def follow_one(self, lt, t, key, direction="out"):
        self.calls.append(("follow_one", lt, t, direction))
        return None


def _fields(cls) -> dict:
    ann = cls.__annotations__
    return {f.name: (ann.get(f.name, "<no annotation>"), f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING) for f in dataclasses.fields(cls)}


def check(ir: dict, sdk) -> dict:
    exp = load_oracle_module("typecheck_oracle").expected(ir)
    res, fails = Counter(), []

    def ok(kind: str, name: str, cond: bool, why: str = ""):
        res[kind + (":pass" if cond else ":fail")] += 1
        if not cond:
            fails.append(f"{kind} {name}: {why}")
    for t, e in exp["objects"].items():
        cls = getattr(sdk, t, None)
        ok("object_exists", t, cls is not None and isinstance(cls, type) and issubclass(cls, Obj), "missing or not an Obj")
        if cls is None:
            continue
        got = _fields(cls)
        ok("object_field_names", t, set(got) == set(e["fields"]), f"fields {sorted(got)} != {sorted(e['fields'])}")
        for name, (a, req) in e["fields"].items():
            ok("object_field_type", f"{t}.{name}", name in got and got[name][0] == a, f"{got.get(name, ('missing',))[0]} != {a}")
            ok("object_field_required", f"{t}.{name}", name in got and got[name][1] == req, "required/optional differs")
        ok("object_meta", t, (cls.TYPE, cls.PK, cls.IMPLEMENTS) == (t, e["pk"], tuple(e["implements"])), "TYPE/PK/IMPLEMENTS differ")
    for i, props in exp["interfaces"].items():
        cls = getattr(sdk, i, None)
        got = {k: v for k, v in getattr(cls, "__annotations__", {}).items() if k != "IFACE"}
        ok("interface", i, cls is not None and got == props, f"{got} != {props}")
    for (t, name), e in exp["accessors"].items():
        cls = getattr(sdk, t, None)
        fn = getattr(cls, name, None) if cls else None
        ok("accessor_exists", f"{t}.{name}", callable(fn), "missing")
        if not callable(fn):
            continue
        ok("cardinality_annotation", f"{t}.{name}", fn.__annotations__.get("return") == e["annotation"], f"{fn.__annotations__.get('return')} != {e['annotation']}")
        rec = _Rec()
        try:
            fn(_probe(cls), rec)
        except Exception as exc:  # noqa: BLE001
            fails.append(f"accessor_call {t}.{name}: {type(exc).__name__} {exc}")
        want = ("follow_one" if e["single"] else "follow", e["link"], t, e["direction"])
        ok("cardinality_behaviour", f"{t}.{name}", rec.calls == [want], f"calls {rec.calls} != {[want]}")
    for t, o in exp["objects"].items():
        cls = getattr(sdk, t, None)
        extra = sorted(n for n in dir(cls) if n.startswith(("out_", "in_")) and (t, n) not in exp["accessors"]) if cls else []
        ok("no_extra_accessors", t, not extra, f"unexpected {extra}")
    for lid, lk in {l["id"]: l for l in ir["link_types"]}.items():
        m = sdk.MANIFEST["links"].get(lid, {})
        ok("link_cardinality_table", lid, m.get("from_cardinality") == [lk["from_cardinality"]["min"], lk["from_cardinality"]["max"]]
           and m.get("to_cardinality") == [lk["to_cardinality"]["min"], lk["to_cardinality"]["max"]], f"{m}")
    for kind, table, prefix, base, other, extra_m in (("function", exp["functions"], "Fn_", FunctionCall, ActionRequest, "propose"),
                                                       ("action", exp["actions"], "Act_", ActionRequest, FunctionCall, "call")):
        for rid, e in table.items():
            cls = getattr(sdk, prefix + rid, None)
            ok(f"{kind}_distinct", rid, cls is not None and issubclass(cls, base) and not issubclass(cls, other) and not hasattr(cls, extra_m),
               f"must derive {base.__name__} only and have no {extra_m}")
            if cls is None:
                continue
            got = _fields(cls)
            ok(f"{kind}_fields", rid, got == {k: (a, req) for k, (a, req) in e["fields"].items()}, f"{got} != {e['fields']}")
            if kind == "action":
                ok("action_meta", rid, (cls.CAPABILITY, cls.IDEMPOTENCY, cls.ID) == (e["capability"], e["idempotency"], rid), "CAPABILITY/IDEMPOTENCY/ID differ")
            else:
                ok("function_meta", rid, cls.ID == rid, "ID differs")
    ids = {k[len("Fn_"):] for k in dir(sdk) if k.startswith("Fn_")}, {k[len("Act_"):] for k in dir(sdk) if k.startswith("Act_")}
    ok("callable_set", "functions", ids[0] == set(exp["functions"]), f"{sorted(ids[0] ^ set(exp['functions']))}")
    ok("callable_set", "actions", ids[1] == set(exp["actions"]), f"{sorted(ids[1] ^ set(exp['actions']))}")
    total = sum(res.values())
    passed = sum(v for k, v in res.items() if k.endswith(":pass"))
    return {"checks": total, "passed": passed, "failed": total - passed, "conformance": (passed / total) if total else 0.0,
            "by_kind": {k.split(":")[0]: sum(v for kk, v in res.items() if kk.startswith(k.split(":")[0] + ":")) for k in sorted(res)},
            "failures": fails[:25]}


def _probe(cls):
    """An instance with every field set to a placeholder (the accessor only reads its key)."""
    vals = {f.name: "k" for f in dataclasses.fields(cls)}
    return cls(**vals)
