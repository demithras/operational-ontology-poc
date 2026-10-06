"""Generic bindings / adapters / seed data for ANY valid IR package (used by property tests).

Nothing here knows a domain: it reads the compiled Model and fabricates type-correct values.
"""
from __future__ import annotations

import random

from eoo_engine import AdapterRegistry, LogicBindings, Principal
from eoo_engine.authority import parse_principal, type_lookup
from eoo_engine.effects import ADAPTER_OPS, routes_to_adapter
from eoo_engine.registry import load_model

ALLOW_ID = "engine-test-universal-allow"
_PRIM = {"string": "s", "integer": 1, "number": 1.5, "boolean": True, "datetime": "2026-01-01T00:00:00+00:00",
         "date": "2026-01-01", "json": {"k": [1]}, "bytes": b"\x00"}


class Impossible(Exception):
    """No type-correct value exists in the current state (e.g. a ref with no target object)."""


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def apply(self, effect, payload):
        self.calls.append(effect["effect_id"])
        return {"ok": True, "effect": effect["effect_id"]}

    def observations(self):
        return []


def value(te, view, model, concrete=False):
    if isinstance(te, str):
        return _PRIM[te]
    (ctor, inner), = te.items()
    if ctor == "optional":
        return value(inner, view, model, concrete) if concrete else None
    if ctor == "list":
        return []
    if model.is_import(inner):
        return "external-key"
    objs = view.list(inner)
    if not objs:
        raise Impossible(f"no {inner} object")
    return objs[0]["key"]


def fresh_key(te, tag: int, n: int):
    base = te["optional"] if isinstance(te, dict) and "optional" in te else te
    if base == "string":
        return f"g{tag}-{n}"
    if base == "integer":
        return tag * 1000 + n
    raise Impossible(f"primary key of type {te!r} cannot be fabricated")


def permissive_variant(pkg: dict) -> dict:
    """Same package plus one universal allow rule referenced by every action (still a valid package)."""
    out = {**pkg, "authority_rules": list(pkg["authority_rules"]) + [
        {"id": ALLOW_ID, "principal_selector": "*", "capability": "*", "resource_selector": "*", "effect": "allow"}]}
    out["actions"] = [{**a, "authority_refs": list(a["authority_refs"]) + ["auth:" + ALLOW_ID]} for a in pkg["actions"]]
    return out


def payload_for(model, eff, counter):
    def build(ctx):
        v = ctx.view
        if routes_to_adapter(eff):
            return {f: "v" for f in (eff.fields or ())}
        op = eff.operation
        if op in ("create", "update", "delete"):
            spec = model.get("object_types", eff.target)
            names = list(eff.fields) if eff.fields is not None else list(spec.props)
            if op == "create":
                counter[0] += 1
                p = {}
                for f in names:
                    pt = spec.props[f]["type"]
                    p[f] = fresh_key(pt, 900 + eff.index, counter[0]) if f == spec.pk else value(pt, v, model)
                return p
            objs = v.list(eff.target)
            if not objs:
                raise Impossible(f"no {eff.target} to {op}")
            if op == "delete":
                return {"$key": objs[-1]["key"]}
            p = {f: value(spec.props[f]["type"], v, model) for f in names
                 if f != spec.pk and not spec.props[f].get("immutable")}
            return {"$key": objs[0]["key"], **p}
        spec = model.get("link_types", eff.target)
        src, dst = v.list(spec.src), v.list(spec.dst)
        if not src or not dst:
            raise Impossible(f"no ends for {eff.target}")
        names = list(eff.fields) if eff.fields is not None else list(spec.props)
        props = {f: value(spec.props[f]["type"], v, model) for f in names}
        return {"$src": [src[0]["type"], src[0]["key"]], "$dst": [dst[-1]["type"], dst[-1]["key"]], **props}
    return build


def seed(eng, model) -> int:
    """Seed up to 2 objects per object type (fixpoint over ref dependencies). Returns objects created."""
    from eoo_engine import EngineError
    pending = [(tag, n, tid, spec) for tag, (tid, spec) in enumerate(sorted(model.all("object_types").items()))
               for n in (1, 2)]
    made, progress = 0, True
    while pending and progress:
        progress = False
        for item in list(pending):
            tag, n, tid, spec = item
            try:
                key = fresh_key(spec.props[spec.pk]["type"], tag, n)
                props = {spec.pk: key}
                for pn, p in spec.props.items():
                    if pn != spec.pk and p["required"]:
                        props[pn] = value(p["type"], eng.read_view(), model, concrete=True)
                eng.seed([{"op": "create", "type": tid, "key": key, "props": props}])
            except (Impossible, EngineError):
                continue
            pending.remove(item)
            made += 1
            progress = True
    return made


def conflicting_policy_refs(model) -> bool:
    by_ref: dict = {}
    for p in model.all("policies").values():
        by_ref.setdefault(p.expr, set()).add(p.decision)
    return any("allow" in d and d & {"deny", "require_approval"} for d in by_ref.values())


def bind_all(pkg: dict, mode: str, rnd: random.Random):
    """(LogicBindings, AdapterRegistry, RecordingAdapter) binding every ref the package needs.
    mode "permissive": every gate passes; mode "random": every binding returns a fixed random value."""
    model = load_model(pkg)
    b, reg, ad, counter = LogicBindings(), AdapterRegistry(), RecordingAdapter(), [0]
    pol_decisions: dict = {}
    for p in model.all("policies").values():
        pol_decisions.setdefault(p.expr, set()).add(p.decision)
    fn_out = {f.impl_ref: f.output for f in reversed(list(model.all("functions").values()))}

    def const(v):
        return lambda *a: v

    for u in dict.fromkeys(model.required):
        k, key = u.kind, u.key
        if b.has(k, key) or (k == "adapter" and reg.lookup(*key.split(":", 1)) is not None):
            continue
        rand = mode == "random"
        if k == "adapter":
            reg.register(*key.split(":", 1), ad)
        elif k == "function":
            out = fn_out[key]
            b.bind(k, key, lambda view, args, out=out: value(out, view, model))
        elif k == "policy":  # random mode is biased towards passing so that later lifecycle stages are reached
            passing = "allow" in pol_decisions[key]
            v = (passing if rnd.random() < 0.8 else not passing) if rand else passing
            b.bind(k, key, const(v))
        elif k in ("precondition", "constraint", "principal_selector", "resource_selector"):
            b.bind(k, key, const(rnd.random() < 0.85 if rand else True))
        elif k == "outcome_predicate":
            b.bind(k, key, const(rnd.choice([True, False, None]) if rand else True))
        elif k == "authority_import":
            b.bind(k, key, const(rnd.choice(["allow", "deny", None]) if rand else "allow"))
        elif k == "policy_import":
            b.bind(k, key, const(rnd.choice(["allow", "deny", "require_approval", "classify", None]) if rand else None))
        elif k == "payload":
            aid, idx = key.rsplit("#", 1)
            b.bind(k, key, payload_for(model, model.get("actions", aid).effects[int(idx)], counter))
    for op in ADAPTER_OPS:  # adapter targets are never left unbound by this helper
        if reg.lookup(op, "*") is None:
            reg.register(op, "*", ad)
    return model, b, reg, ad


def principals(model, eng) -> list:
    look = type_lookup(model)
    roles, rels = set(), set()
    for r in model.all("authority_rules").values():
        sel = parse_principal(r.raw_principal, look)
        if sel[0] == "role":
            roles.add(sel[1])
        if sel[0] == "relation":
            for o in eng.read_view().list(sel[1]):
                rels.add((o["type"], o["key"], sel[2]))
    return [Principal("tester", roles, rels), Principal("second", roles, rels)]


def inputs_for(spec, view, model):
    """Type-correct inputs for an action, or None when the current state cannot provide them."""
    try:
        return {p.pname: value(p.type, view, model, concrete=True) for p in spec.inputs if p.required}
    except Impossible:
        return None
