"""Load a generated package into the Engine through generic dispatch; domain-id-rename invariance; dispatch smoke."""
from __future__ import annotations

import copy
from collections import Counter

from eoo_engine import AdapterRegistry, Engine, EngineError, LogicBindings
from eoo_engine.effects import ADAPTER_OPS
from eoo_engine.registry import DISPATCH_TABLE, load_model

KINDS = tuple(DISPATCH_TABLE)


class _Null:
    """Inert adapter and logic stubs: loading needs every ref bound, it never calls them."""

    def apply(self, effect, payload):
        return {}

    def observations(self):
        return []


def stub_bindings(pkg: dict):
    model = load_model(pkg)
    b, reg, ad = LogicBindings(), AdapterRegistry(), _Null()
    for u in dict.fromkeys(model.required):
        if u.kind == "adapter":
            reg.register(*u.key.split(":", 1), ad)
        else:
            b.bind(u.kind, u.key, lambda *a, **k: None)
    for op in ADAPTER_OPS:
        if reg.lookup(op, "*") is None:
            reg.register(op, "*", ad)
    return b, reg, model


def shape(model) -> dict:
    return {"sizes": {k: len(model.kinds.get(k, {})) for k in KINDS},
            "required_by_kind": dict(sorted(Counter(u.kind for u in model.required).items()))}


def load_case(pkg: dict) -> dict:
    """Engine(pkg, ...) through DISPATCH_TABLE. Returns {loaded, sizes_match, unbound, dispatch_smoke, error}."""
    try:
        b, reg, model = stub_bindings(pkg)
        eng = Engine(pkg, b, reg)
    except (EngineError, Exception) as e:  # noqa: BLE001 - a load failure is a recorded result, not a crash
        return {"loaded": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    sh = shape(eng.model)
    smoke = []
    for kind, op in (("object_types", "list"), ("interfaces", "query")):
        if pkg[kind]:
            try:
                eng.dispatch(kind, op, pkg[kind][0]["id"])
                smoke.append(f"{kind}.{op}")
            except Exception as e:  # noqa: BLE001
                return {"loaded": False, "error": f"dispatch {kind}.{op}: {type(e).__name__}: {str(e)[:120]}"}
    return {"loaded": True, "sizes_match": sh["sizes"] == {k: len(pkg[k]) for k in KINDS}, "shape": sh,
            "unbound": len(set(eng.model.required)), "dispatch_smoke": smoke}


def rename_domain(pkg: dict, tag: str) -> dict:
    out = copy.deepcopy(pkg)
    out["package_id"] = f"renamed-{tag}"
    out["domain_id"] = f"renamed-domain-{tag}"
    return out


def rename_invariant(pkg: dict) -> dict:
    """Package/domain ids are identities, not semantics: renaming them must leave the compiled shape unchanged."""
    a, b = load_case(pkg), load_case(rename_domain(pkg, "q"))
    same = a.get("loaded") and b.get("loaded") and a["shape"] == b["shape"]
    return {"invariant": bool(same), "before": a.get("shape"), "after": b.get("shape")}
