"""Security differential: capability sets of the generated surface vs the independent authority oracle."""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

from eoo_exp.util import ROOT
from eoo_toolchain.runtime import World

from . import opaque

DIMS = ("visible", "queryable", "actionable", "approvable", "tools")


def load_oracle_module(name: str):
    """Import oracles/h21/<name>.py by path (the oracle tree is deliberately not on the package path)."""
    path = ROOT / "oracles/h21" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"oracles_h21_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def surface_sets(surf_mod, ir: dict, case: dict, ops: dict) -> dict:
    w = World({t: list(v) for t, v in case["world"]["objects"].items()}, dict(case["world"]["flags"]))
    s = surf_mod.AgentSurface(None, case["principal"], w, ops, registered=case["registered"])
    return s.capabilities()


def run(ir: dict, surf_mod, cases: list, sample_rows: int = 12) -> dict:
    ref = load_oracle_module("authority_oracle").Reference(ir)
    ops = opaque.make(ir)
    mism, per_dim, compared, stats = [], Counter(), Counter(), Counter()
    for c in cases:
        got, want = surface_sets(surf_mod, ir, c, ops), ref.sets(c)
        bad = [d for d in DIMS if got[d] != want[d]]
        compared.update({d: len(want[d]) for d in DIMS})
        per_dim.update(bad)
        stats["cases"] += 1
        stats["registered"] += c["registered"]
        stats["delegated"] += c["principal"]["delegated_by"] is not None
        stats["with_allowed_action"] += bool(want["actionable"])
        stats["with_denied_binding_space"] += bool(c["registered"])
        stats["selector_fault_world"] += bool(c["world"]["flags"]["fault"])
        stats["delegated_with_allowed_action"] += bool(want["actionable"]) and c["principal"]["delegated_by"] is not None
        stats["with_approval_capability"] += bool(want["approvable"])
        if bad:
            mism.append({"dims": bad, "over": sorted(set(got[bad[0]]) - set(want[bad[0]]))[:3],
                         "under": sorted(set(want[bad[0]]) - set(got[bad[0]]))[:3], "pid": c["principal"]["pid"]})
    return {"cases": len(cases), "mismatching_cases": len(mism), "mismatches_by_dimension": dict(per_dim),
            "capabilities_compared": dict(compared), "overexposed_total": sum(len(m["over"]) > 0 for m in mism),
            "underexposed_total": sum(len(m["under"]) > 0 for m in mism), "coverage": dict(stats),
            "mismatch_sample": mism[:sample_rows]}
