"""Interface polymorphism: ONE generic interface tool per interface serves every implementer, with no per-type code."""
from __future__ import annotations

import copy
import inspect
import tempfile
from collections import Counter

from eoo_toolchain import build, load_generated
from eoo_toolchain.naming import ident
from eoo_toolchain.runtime import EngineClient


def tool_source(surf_mod, iface: str) -> str:
    return inspect.getsource(surf_mod.AgentSurface.QUERY_TOOLS["query_" + ident(iface)][1])


def implementers_of(ir: dict, iface: str) -> list:
    return sorted(o["id"] for o in ir["object_types"] if iface in o.get("implements", []))


def against_engine(ir: dict, surf_mod, engine) -> list:
    client, view, rows = EngineClient(engine), engine.read_view(), []
    for i in ir["interfaces"]:
        impls = implementers_of(ir, i["id"])
        fn = surf_mod.AgentSurface.QUERY_TOOLS["query_" + ident(i["id"])][1]
        got = Counter(type(o).__name__ for o in fn(client))
        store = {t: len(view.list(t)) for t in impls}
        src = tool_source(surf_mod, i["id"])
        rows.append({"interface": i["id"], "implementers": impls, "implementer_count": len(impls), "store_objects": store,
                     "tool_returned_by_type": dict(got), "types_served": sum(1 for t in impls if got.get(t)),
                     "types_with_objects": sum(1 for t in impls if store[t]),
                     "equals_store": all(got.get(t, 0) == store[t] for t in impls) and set(got) <= set(impls),
                     "tool_source_names_an_implementer": [t for t in impls if t in src], "tool_source": src.strip()})
    return rows


class _Fake:
    def __init__(self, records):
        self.records = records

    def interface_query(self, iface):
        return list(self.records.get(iface, []))


def add_implementers(ir: dict, iface: str, names: list) -> dict:
    out = copy.deepcopy(ir)
    base = next(i for i in out["interfaces"] if i["id"] == iface)
    for n in names:
        props = [{"name": "synth_id", "type": "string", "required": True, "immutable": True}] + [
            {"name": p["name"], "type": p["type"], "required": True, "immutable": p.get("immutable", False)} for p in base["required_properties"]]
        out["object_types"].append({"id": n, "primary_key": "synth_id", "properties": props, "implements": [iface]})
    return out


def after_adding_types(ir: dict, iface: str, original_src: str) -> dict:
    """Add two NEW object types implementing ``iface``, regenerate, and show the generic tool is byte-identical and serves them."""
    names = ["SynthAlpha", "SynthBeta"]
    ir2 = add_implementers(ir, iface, names)
    d = tempfile.mkdtemp(prefix="h21-poly-")
    inv = build(ir2, d)
    sdk, _caps, surf = load_generated(d, inv["package"])
    recs = [{"type": n, "key": f"{n}-1", "props": {"synth_id": f"{n}-1"}} for n in names]
    fn = surf.AgentSurface.QUERY_TOOLS["query_" + ident(iface)][1]
    got = fn(_Fake({iface: recs}))
    src = tool_source(surf, iface)
    return {"interface": iface, "added_types": names, "tool_source_identical": src.strip() == original_src.strip(),
            "returned_types": sorted(type(o).__name__ for o in got), "serves_new_types": sorted(type(o).__name__ for o in got) == sorted(names)}
