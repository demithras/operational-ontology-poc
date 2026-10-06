"""Alias-invariance probe: the SAME synthetic definition run under neutral ids and under REAL domain identifiers.

A generic Engine cannot tell the runs apart; one that branches on a package / action / type / role name behaves
differently for the aliased run and disagrees with the oracle (or with the neutral run).
"""
from __future__ import annotations

import json

from eoo_exp.util import ROOT

from . import synth, synth_run


def alias_modes() -> dict:
    """neutral + one mode per domain, built from the first resource of each kind of that domain's IR."""
    modes = {"neutral": {}}
    for dom, f, act in (("manufacturing", "manufacturing/ir.json", "transfer_inventory"), ("project", "project/ir.v2.json", "create_hypothesis")):
        ir = json.loads((ROOT / "domains" / f).read_text())
        sel = [(r["principal_selector"], r["capability"]) for r in ir["authority_rules"]]
        roles = sorted({s.split(":", 1)[-1].split("#")[-1] for s, c in sel if c.startswith("action:")})
        appr = sorted({s.split(":", 1)[-1].split("#")[-1] for s, c in sel if c.startswith("approval:")})
        modes[dom] = {"pkg": ir["package_id"], "dom": ir.get("domain_id", dom), "T": ir["object_types"][0]["id"],
                      "S": ir["object_types"][1]["id"], "L": ir["link_types"][0]["id"], "fn": ir["functions"][0]["id"],
                      "act": act, "pol": ir["policies"][0]["id"], "obs": ir["observation_types"][0]["id"],
                      "actor": roles[0], "approver": next(r for r in [*appr, *reversed(roles), "approver"] if r != roles[0])}
    return modes


def run_all_modes(d: dict, modes: dict) -> dict:
    out = {}
    for name, alias in modes.items():
        synth.ALIAS.clear()
        synth.ALIAS.update(alias)
        try:
            r = synth_run.run(d)
        finally:
            synth.ALIAS.clear()
        out[name] = {"state": r["observed_state"], "history": r["history"], "mismatches": r["mismatches"]}
    return out


def probe(defs: list) -> dict:
    modes = alias_modes()
    rows, bad = [], []
    for d in defs:
        r = run_all_modes(d, modes)
        base = r["neutral"]
        diff = [m for m, v in r.items() if v != base or v["mismatches"]]
        rows.append(len(diff) == 0)
        if diff and len(bad) < 5:
            bad.append({"sha": synth_run.definition_sha(d), "modes_differing": diff, "detail": {m: r[m] for m in diff}})
    return {"definitions": len(defs), "modes": sorted(modes), "alias_ids": {m: a for m, a in modes.items() if a},
            "disagreements": rows.count(False), "examples": bad}
