"""Run the registered mutants against the detectors; control (clean) before and after; record the failing signal."""
from __future__ import annotations

import contextlib
import json

from eoo_exp.util import ROOT

from . import mutants as M
from .detectors import audit_sources, changed_is_clean, kernel_diff
from .kernel import live_snapshot
from .loadcheck import rename_invariant

SIGNALS = ("kernel_new_kind", "kernel_removed_kind", "kernel_handler_changed", "audit_branch", "audit_literal",
           "rename_invariance_broken")


def detect(before: dict, *, overrides=None, schema_text=None, ctx=None, sample_pkgs=()) -> dict:
    ir = json.loads((ROOT / "domains/manufacturing/ir.json").read_text())
    with (ctx() if ctx else contextlib.nullcontext()):
        diff = kernel_diff(before, live_snapshot(schema_text=schema_text))
        inv = [rename_invariant(ir)["invariant"]] + [rename_invariant(p)["invariant"] for p in sample_pkgs]
    audit = audit_sources(overrides)
    fired = {"kernel_new_kind": bool(diff["new_kernel_primitive_kinds"]), "kernel_removed_kind": bool(diff["removed_kinds"]),
             "kernel_handler_changed": bool(diff["dispatch_handlers_changed"]),
             "audit_branch": audit["domain_identity_branches"] > 0, "audit_literal": audit["domain_identity_literals"] > 0,
             "rename_invariance_broken": not all(inv)}
    return {"signals": fired, "any_signal": any(fired.values()), "new_kinds": diff["new_kernel_primitive_kinds"],
            "removed_kinds": diff["removed_kinds"], "handlers_changed": diff["dispatch_handlers_changed"],
            "audit_branches": audit["domain_identity_branches"], "audit_literals": audit["domain_identity_literals"],
            "audit_hit_examples": [h for s in audit["scopes"].values() for h in s["hits"]][:3],
            "rename_invariance_checked": len(inv), "rename_invariant_all": all(inv)}


def registry(before: dict, sample_pkgs=()) -> list[dict]:
    """(id, class, target, expected signal, kwargs for detect)."""
    src = M.src_mutations()
    return [
        {"id": "M1_static_domain_id_compare_in_registry", "class": "domain_special_case", "target": True,
         "expect": "audit_branch", "kw": {"overrides": src["M1_static_domain_id_compare_in_registry"]}},
        {"id": "M2_runtime_domain_branch_in_loader", "class": "domain_special_case", "target": True,
         "expect": "rename_invariance_broken", "kw": {"ctx": M.runtime_domain_branch}},
        {"id": "M3_new_dispatch_kind", "class": "new_primitive_kind", "target": True,
         "expect": "kernel_new_kind", "kw": {"ctx": M.new_dispatch_kind}},
        {"id": "M4_new_schema_resource_array", "class": "new_primitive_kind", "target": True,
         "expect": "kernel_new_kind", "kw": {"schema_text": M.schema_with_new_array()}},
        {"id": "M5_removed_dispatch_kind", "class": "kernel_shrink", "target": False,
         "expect": "kernel_removed_kind", "kw": {"ctx": M.removed_dispatch_kind}},
        {"id": "M6_swapped_handler", "class": "handler_swap", "target": False,
         "expect": "kernel_handler_changed", "kw": {"ctx": M.swapped_handler}},
        {"id": "M7_static_domain_dict_key_in_validator", "class": "domain_special_case", "target": False,
         "expect": "audit_branch", "kw": {"overrides": src["M7_static_domain_dict_key_in_validator"]}},
        {"id": "M8_static_resource_id_branch_in_pipeline", "class": "domain_special_case", "target": False,
         "expect": "audit_literal", "kw": {"overrides": src["M8_static_resource_id_branch_in_pipeline"]}},
    ]


def run_mutations(before: dict, sample_pkgs=()) -> dict:
    control = detect(before, sample_pkgs=sample_pkgs)
    rows = []
    for m in registry(before, sample_pkgs):
        res = detect(before, sample_pkgs=sample_pkgs, **m["kw"])
        rows.append({"id": m["id"], "class": m["class"], "target": m["target"], "expected_signal": m["expect"],
                     "killed": bool(res["signals"][m["expect"]]), "signals_fired": [k for k, v in res["signals"].items() if v],
                     "detail": {k: res[k] for k in ("new_kinds", "removed_kinds", "handlers_changed", "audit_branches",
                                                    "audit_literals", "audit_hit_examples", "rename_invariant_all")}})
    after = detect(before, sample_pkgs=sample_pkgs)
    tgt = [r for r in rows if r["target"]]
    summary = {"target_total": len(tgt), "target_killed": sum(r["killed"] for r in tgt),
               "kill_rate": (sum(r["killed"] for r in tgt) / len(tgt)) if tgt else 0.0,
               "all_total": len(rows), "all_killed": sum(r["killed"] for r in rows),
               "target_classes_present": sorted({r["class"] for r in tgt})}
    return {"controls": {"clean": not control["any_signal"], "clean_after_restore": not after["any_signal"],
                         "control": control, "after_restore": after},
            "mutants": rows, "summary": summary}
