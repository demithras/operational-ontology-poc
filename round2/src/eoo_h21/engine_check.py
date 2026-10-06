"""Secondary check: the generated surface (real domain selector bindings) and the oracle against the Engine's own
authority decision, over a live booted Engine of one domain. Reported next to, never instead of, the oracle differential."""
from __future__ import annotations

import json
from types import SimpleNamespace

from eoo_engine import Principal
from eoo_engine.authority import Resource
from eoo_toolchain.runtime import EngineClient, World

from . import cases
from .differential import load_oracle_module


def real_opaque(engine) -> dict:
    return {key: engine.bindings.get(kind, key) for kind, key in engine.bindings.keys() if kind in ("principal_selector", "resource_selector")}


def prereg_keys(engine, ops: dict, objs: dict) -> list:
    fn = ops.get("Threshold:preregistered")
    if fn is None:
        return []
    view = engine.read_view()
    return sorted(k for k in objs.get("Threshold", [])
                  if fn(SimpleNamespace(resources=(SimpleNamespace(declared="Threshold", key=k, actual="Threshold"),), view=view, principal=None, capability="")))


def run(engine, ir: dict, surf_mod, n: int, seed: int) -> dict:
    client = EngineClient(engine)
    objs = {o["id"]: [r["key"] for r in engine.read_view().list(o["id"])] for o in ir["object_types"]}
    ops = real_opaque(engine)
    pre = prereg_keys(engine, ops, objs)
    ref = load_oracle_module("authority_oracle").Reference(ir)
    cs = cases.unique_cases(ir, n, seed, fixed_world=objs)
    bad, decisions, actionable = [], 0, 0
    view = engine.read_view()
    for c in cs:
        c["registered"] = True
        c["world"]["flags"] = {"preregistered": pre, "fault": False}
        w = World({t: list(v) for t, v in objs.items()}, dict(c["world"]["flags"]), view=view)
        s = surf_mod.AgentSurface(client, c["principal"], w, ops)
        got = set(s.capabilities()["actionable"])
        want_oracle = set(ref.sets(c)["actionable"])
        who = Principal.from_plain(c["principal"])
        eng_set = set()
        for aid, a in sorted(ref.actions.items()):
            spec = engine.model.get("actions", aid)
            for b, res in ref.bindings(a, objs):
                decisions += 1
                d = engine.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who, capability="action:" + aid,
                                    resources=tuple(Resource(r["declared"], r["key"], r["actual"]) for r in res), view=view)
                if d.allowed:
                    eng_set.add(f"{aid}|{json.dumps(b, sort_keys=True, separators=(',', ':'))}")
        actionable += len(eng_set)
        if not (got == want_oracle == eng_set):
            bad.append({"pid": c["principal"]["pid"], "surface_only": sorted(got - eng_set)[:3], "oracle_only": sorted(want_oracle - eng_set)[:3],
                        "engine_only": sorted(eng_set - got)[:3]})
    return {"cases": len(cs), "unique_cases": len({cases.case_sha(c) for c in cs}), "decisions_compared": decisions,
            "engine_allowed_total": actionable, "disagreements": len(bad), "disagreement_sample": bad[:8],
            "preregistered_thresholds_from_engine": len(pre), "opaque_selectors_bound_by_domain": sorted(ops)}
