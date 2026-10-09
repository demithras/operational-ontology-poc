"""Scripted-ledger scenarios for C28-2: one case per (scenario, system) with a fixed step list; the HARNESS writes the scripted
ledger rows itself (Player.s_script) so rules D2/D3 are reachable even against a correct variant."""
from __future__ import annotations

import copy

from .gen_case import build_case
from .gen_params import draw_params

REQ = [{"op": "request", "i": 0}, {"op": "dispatch"}]
SCEN = {   # name -> (prims, steps after REQ)
    "ok": ([], [{"op": "reconcile", "fault": None}, {"op": "final"}]),
    "fail": (["O1"], [{"op": "final"}]),
    "pend": (["L1"], [{"op": "reconcile", "fault": None}, {"op": "final"}]),
    "d2": (["L1"], [{"op": "script", "i": 0, "what": "write_other"}, {"op": "reconcile", "fault": None}, {"op": "final"}]),
    "d3": ([], [{"op": "script", "i": 0, "what": "write_exact"}, {"op": "reconcile", "fault": None}, {"op": "final"}]),
    "u": ([], [{"op": "reconcile", "fault": {"kind": "unavailable", "k": 0}}, {"op": "reconcile", "fault": None}, {"op": "final"}]),
    "d1": (["L1"], [{"op": "script", "i": 0, "what": "write_other"}, {"op": "reconcile", "fault": None},
                    {"op": "reconcile", "fault": {"kind": "lagging", "k": 20}}, {"op": "final"}]),
    "stale": ([], [{"op": "reconcile", "fault": None}, {"op": "reconcile", "fault": {"kind": "lagging", "k": 20}}, {"op": "final"}]),
}


def scenario_cases(seed: int) -> list[dict]:
    """One OK-request base case per system (full / effects_only / none), crossed with every scenario."""
    params, _ = draw_params(seed + 31, 400, "control")
    st, bases = {}, {}
    for p in params:
        if p["system"] in bases or p["approved_flow"] or p["denied"]:
            continue
        c = build_case(p, seed + 31, st)
        if c is not None and c["requests"][0]["expect"] == "commit":
            bases[p["system"]] = c
    out = []
    for sysname, base in sorted(bases.items()):
        for name, (prims, tail) in SCEN.items():
            c = copy.deepcopy(base)
            c.update(prims=prims, steps=REQ + tail, crash=None, fault=None, replay=False, kind="byz", main=prims[0] if prims else "H0",
                     k=2, reps=2)
            c["requests"] = c["requests"][:1]
            c["scenario"] = name
            out.append(c)
    return out
