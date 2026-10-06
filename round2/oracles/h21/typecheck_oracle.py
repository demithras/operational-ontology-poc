"""Independent IR type checker for H21: what a generated SDK must contain, derived straight from the IR.

Annotation text uses the SDK's documented spelling (docs: Key for references, Optional[...] for non-required and optional
types, list[...], Literal[...] for enum constraints, Any for json). Imports nothing from the Engine, Toolchain or domains.
"""
from __future__ import annotations

PRIM = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "datetime": "str", "date": "str",
        "json": "Any", "bytes": "bytes"}


def ann(te) -> str:
    if isinstance(te, str):
        return PRIM[te]
    ((c, inner),) = te.items()
    return {"ref": lambda: "Key", "list": lambda: f"list[{ann(inner)}]", "optional": lambda: f"Optional[{ann(inner)}]"}[c]()


def prop_ann(p: dict) -> str:
    enums = [c[5:].split("|") for c in (p.get("constraints") or []) if isinstance(c, str) and c.startswith("enum:")]
    base = ("Literal[" + ", ".join(repr(v) for v in enums[0]) + "]") if enums else ann(p["type"])
    return base if p.get("required") or base.startswith("Optional[") else f"Optional[{base}]"


def param_ann(p: dict) -> str:
    base = ann(p["type"])
    return base if p.get("required", True) or base.startswith("Optional[") else f"Optional[{base}]"


def implementers(ir: dict, end: str) -> list:
    ids = [o["id"] for o in ir["object_types"]]
    return [end] if end in ids else sorted(o["id"] for o in ir["object_types"] if end in o.get("implements", []))


def expected(ir: dict) -> dict:
    """Everything a conformant SDK must show, keyed by what is checked."""
    objs = {o["id"]: {"pk": o["primary_key"], "implements": list(o.get("implements", [])),
                      "fields": {p["name"]: (prop_ann(p), bool(p.get("required"))) for p in o["properties"]}} for o in ir["object_types"]}
    ifaces = {i["id"]: {p["name"]: prop_ann(p) for p in i["required_properties"]} for i in ir["interfaces"]}
    accessors = {}
    for lk in ir["link_types"]:
        for end, name, card, other, direction in ((lk["from"], "out_", lk["from_cardinality"], lk["to"], "out"),
                                                  (lk["to"], "in_", lk["to_cardinality"], lk["from"], "in")):
            single = card["max"] == 1
            for t in implementers(ir, end):
                accessors[(t, name + lk["id"])] = {"link": lk["id"], "direction": direction, "single": single,
                                                   "annotation": f"Optional[{other}]" if single else f"list[{other}]",
                                                   "min": card["min"], "max": card["max"]}
    fns = {f["id"]: {"fields": {p["name"]: (param_ann(p), p.get("required", True)) for p in f["inputs"]}} for f in ir["functions"]}
    acts = {a["id"]: {"fields": {p["name"]: (param_ann(p), p.get("required", True)) for p in a["inputs"]},
                      "capability": "action:" + a["id"], "idempotency": a["idempotency"]} for a in ir["actions"]}
    return {"objects": objs, "interfaces": ifaces, "accessors": accessors, "functions": fns, "actions": acts}
