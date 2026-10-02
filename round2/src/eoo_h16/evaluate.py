"""Frozen H16 evaluator: evidence directory -> verdict.json. Every contract clause is one named predicate with numbers.

Numbers are RECOMPUTED from the raw evidence (snapshots, hit lists, per-case rows, mutant rows), never copied from a
summary field; a summary that disagrees with its raw data is reported as a problem and blocks SUPPORTED.
Missing / unreadable evidence can never produce SUPPORTED.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, git, sha_file

from .audit import BRANCH
from .detectors import kernel_diff
from .run import BEFORE_REV, HID, REQUIRED

SUPPORT = {
    "S1": "0 new kernel primitive kinds after Project Ontology",
    "S2": "0 domain-identity branches in compiler/core runtime (static audit and rename-invariance)",
    "S3": "100% of registered Domain 2 requirements compile through allowed generic resource kinds",
    "S4": "Registered branch-detection mutation is caught (all registered mutants killed, controls clean)",
    "S5": ">= 2,000 unique mixed-domain generated packages validate and load through generic dispatch with 0 failures",
}
REJECT = {
    "R1": "A new kernel primitive kind is present after Domain 2 (kernel diff)",
    "R2": "A domain-identity semantic branch exists in compiler/core runtime (static audit)",
    "R3": "Generic runtime behaviour depends on domain identity (rename-invariance broken on a real or generated package)",
}
INCONCLUSIVE = {
    "I1": "Project Ontology omits a required strong-model object/link/lifecycle/rule/governance requirement",
    "I2": "Fewer unique mixed-domain valid+loaded cases than the frozen minimum",
    "I3": "Generated mixed-domain packages failed to validate/load, or the harness errored (extension, see notes)",
}
INVALID = {
    "V1": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
    "V2": "Evidence records disagree on commit / seed / corpus hash",
    "V3": "Harness self-check failed (mutation control not clean, working tree differs from HEAD, snapshot not from the registered rev)",
    "V4": "Kernel freeze snapshot differs from the frozen files (kernel kinds, schema hash)",
}


def _rev(rev: str) -> str:
    return git("rev-parse", f"{rev}^{{commit}}").strip()


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H16"]
    prereg = json.loads((root / "protocol/ENGINE_PREREG.json").read_text())["kernel_snapshot"]["kernel_resource_kinds"]
    fz = {f["path"]: f["sha256"] for f in json.loads((root / "protocol/FREEZE.json").read_text())["files"]}
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th}
    g, P = sc.g, pay.get

    kb, ka, cd = P("kernel-before.json"), P("kernel-after.json"), P("core-diff.json")
    diff = None
    if kb and ka:
        diff = kernel_diff(kb["snapshot"], ka["snapshot"])
        n["new_kernel_primitive_kinds"] = diff["new_kernel_primitive_kinds"]
        n["new_kernel_primitive_kind_count"] = diff["new_kernel_primitive_kind_count"]
        n["removed_kinds"], n["handlers_changed"] = diff["removed_kinds"], diff["dispatch_handlers_changed"]
        n["schema_unchanged"], n["schema_defs_added"] = diff["schema_unchanged"], diff["schema_defs_added"]
        n["dispatch_kinds_equal_schema_arrays_after"] = diff["dispatch_kinds_equal_schema_arrays"]
        n["domains_arrays_not_kernel_kinds"] = {k: v["arrays_not_kernel_kinds"] for k, v in ka["domain_usage"].items()}
        n["domains_keys_not_in_schema"] = {k: v["top_level_keys_not_in_schema"] for k, v in ka["domain_usage"].items()}
        n["domains_engine_compiled_every_resource"] = {k: v["engine_compiled_every_resource"] for k, v in ka["domain_usage"].items()}
    if cd and diff is not None:
        if cd.get("new_kernel_primitive_kind_count") != diff["new_kernel_primitive_kind_count"]:
            problems.append("core-diff.json new-kind count disagrees with the recomputed diff of the snapshots")
        cov = cd["domain2_requirement_coverage"]
        n["requirements_total"], n["requirements_ok"] = cov["total"], sum(1 for r in cov["requirements"] if r["ok"])
        n["requirements_failed"] = [r["id"] for r in cov["requirements"] if not r["ok"]]
        n["unwired_policy_or_authority_carriers"] = cov["unwired_policy_or_authority_carriers"]
        n["baseline_contextual"] = cd["baseline_contextual"]
    audit = P("domain-branch-audit.json")
    if audit:
        counted = [h for name, s in audit["scopes"].items() if name in ("engine_core", "ir_core") for h in s["hits"]]
        n["audit_branch_hits"] = sum(h["position"] in BRANCH for h in counted)
        n["audit_literal_hits"] = len(counted)
        n["audit_files_scanned"] = {k: s["files_scanned"] for k, s in audit["scopes"].items()}
        n["audit_string_constants_scanned"] = sum(s["string_constants_scanned"] for k, s in audit["scopes"].items() if k in ("engine_core", "ir_core"))
        n["audit_info_scopes_hits"] = {k: len(s["hits"]) for k, s in audit["scopes"].items() if k not in ("engine_core", "ir_core")}
        n["real_domain_rename_broken"] = sorted(k for k, v in audit.get("rename_invariance_real_domains", {}).items() if not v)
        n["real_domain_rename_checked"] = len(audit.get("rename_invariance_real_domains", {}))
        if audit["domain_identity_branches"] != n["audit_branch_hits"]:
            problems.append("audit summary branch count disagrees with its hit list")
    gen = P("mixed-domain-generated.json")
    if gen:
        rows = gen["cases"]
        ok = lambda r: r["valid"] and r["oracle_legal"] and r["loaded"] and r["sizes_match"] and r["mixes_both"]  # noqa: E731
        n["generated_unique_cases"] = len({r["sha"] for r in rows})
        n["generated_rows"] = len(rows)
        n["generated_valid_loaded_mixed"] = sum(1 for r in rows if ok(r))
        n["generated_failures_recomputed"] = sum(1 for r in rows if not ok(r) or r.get("rename_invariant") is False)
        n["generated_failures_recorded"] = len(gen["failures"])
        n["generated_harness_errors"] = sum(1 for f in gen["failures"] if "harness_error" in f)
        n["generated_rename_checked"] = sum("rename_invariant" in r for r in rows)
        n["generated_rename_broken"] = sum(r.get("rename_invariant") is False for r in rows)
        n["generated_by_variant"] = gen["by_variant"]
        n["generated_cross_link_cases"] = sum(bool(r["cross_added"].get("link_types")) for r in rows)
        n["generated_import_cases"] = sum(r["variant"] != "merged_local" for r in rows)
        if n["generated_failures_recomputed"] != n["generated_failures_recorded"] - n["generated_harness_errors"]:
            problems.append("generated failure list disagrees with the per-case rows")
    mut = P("mutation-results.json")
    if mut:
        tgt = [m for m in mut["mutants"] if m["target"]]
        n["mutation_target_total"], n["mutation_target_killed"] = len(tgt), sum(m["killed"] for m in tgt)
        n["mutation_kill_rate"] = (n["mutation_target_killed"] / len(tgt)) if tgt else 0.0
        n["mutation_classes_present"] = sorted({m["class"] for m in tgt})
        n["mutation_survivors"] = [m["id"] for m in mut["mutants"] if not m["killed"]]
        n["mutation_controls_clean"] = [mut["controls"]["clean"], mut["controls"]["clean_after_restore"]]
        n["mutation_failing_signal_by_mutant"] = {m["id"]: m["signals_fired"] for m in mut["mutants"]}

    # ------------------------------------------------------------------ predicates (None = unknown)
    def has(*k):
        return all(x in n for x in k)

    s1 = (n["new_kernel_primitive_kind_count"] <= th["max_new_kernel_primitive_kinds"] and n["dispatch_kinds_equal_schema_arrays_after"]
          and not n["removed_kinds"] and not n["handlers_changed"] and not n["schema_defs_added"]
          and not any(n["domains_arrays_not_kernel_kinds"].values()) and not any(n["domains_keys_not_in_schema"].values())) if has("new_kernel_primitive_kind_count") else None
    r1 = (n["new_kernel_primitive_kind_count"] > th["max_new_kernel_primitive_kinds"]) if has("new_kernel_primitive_kind_count") else None
    r2 = (n["audit_branch_hits"] > th["max_domain_identity_core_branches"]) if has("audit_branch_hits") else None
    r3 = (n["generated_rename_broken"] > 0 or bool(n["real_domain_rename_broken"])) if has("generated_rename_broken", "real_domain_rename_broken") else None
    s2 = (n["audit_branch_hits"] <= th["max_domain_identity_core_branches"] and n["audit_literal_hits"] == 0
          and n["generated_rename_broken"] == 0 and n["generated_rename_checked"] > 0
          and not n["real_domain_rename_broken"] and n["real_domain_rename_checked"] == 3
          and n["audit_string_constants_scanned"] > 1000) if has("audit_branch_hits", "generated_rename_broken", "real_domain_rename_broken") else None
    s3 = (n["requirements_total"] > 0 and n["requirements_ok"] == n["requirements_total"]
          and all(n["domains_engine_compiled_every_resource"].values())) if has("requirements_total", "domains_engine_compiled_every_resource") else None
    s4 = (n["mutation_kill_rate"] >= th["required_mutation_kill_rate"]
          and {"domain_special_case", "new_primitive_kind"} <= set(n["mutation_classes_present"])
          and all(n["mutation_controls_clean"]) and not n["mutation_survivors"]) if has("mutation_kill_rate") else None
    min_n = max(th["min_generated_mixed_cases"], json.loads((root / "hypotheses/h16/contract.json").read_text())["experiment"]["minimum_runs"])
    s5 = (n["generated_valid_loaded_mixed"] >= min_n and n["generated_failures_recomputed"] == 0
          and n["generated_harness_errors"] == 0) if has("generated_valid_loaded_mixed") else None
    i1 = (n["requirements_ok"] < n["requirements_total"]) if has("requirements_total") else None
    i2 = (n["generated_unique_cases"] < min_n or n["generated_valid_loaded_mixed"] < min_n) if has("generated_unique_cases") else None
    i3 = (n["generated_failures_recomputed"] > 0 or n["generated_harness_errors"] > 0) if has("generated_failures_recomputed") else None

    wt = g(ka, "working_tree", default={})
    bsnap = g(kb, "snapshot", default={})
    v3 = []
    if mut is not None and not all(n["mutation_controls_clean"]):
        v3.append("mutation control not clean")
    if ka is not None and not all(wt.values()):
        v3.append(f"working tree differs from HEAD: {wt}")
    if kb is not None and bsnap.get("git_commit") != _rev(BEFORE_REV):
        v3.append("kernel-before is not the registered before revision")
    v4 = []
    if kb is not None:
        if sorted(bsnap["kernel_resource_kinds"]) != sorted(prereg):
            v4.append("kernel-before kinds differ from ENGINE_PREREG")
        if bsnap["ir_schema_blob_sha256"] != fz.get("ontology/ir.schema.json") or sha_file(root / "ontology/ir.schema.json") != fz.get("ontology/ir.schema.json"):
            v4.append("ir.schema.json differs from FREEZE.json")
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5}),
            "reject_if": sc.rows(REJECT, {"R1": r1, "R2": r2, "R3": r3}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1, "I2": i2, "I3": i3}),
            "invalid_if": sc.rows(INVALID, {"V1": bool(wrong), "V2": len(ident) > 1, "V3": bool(v3), "V4": bool(v4)})}
    complete = not problems
    out = sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not wrong and len(ident) <= 1 and not v3 and not v4,
                    complete=complete, sample_sufficient=(i1 is False and i2 is False and i3 is False),
                    reject_hit=any(x is True for x in (r1, r2, r3)), support_hit=all(x is True for x in (s1, s2, s3, s4, s5)),
                    predicates=pred, numbers=n, problems=problems,
                    extra={"protocol_mismatches": {"records_with_wrong_hashes": wrong, "disagreeing_provenance": len(ident) > 1,
                                                   "harness_self_check": v3, "kernel_freeze": v4},
                           "protocol": {"freeze_sha256": freeze_hash()},
                           "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
                           "evaluator_sha256": sha_file(Path(__file__)),
                           "interpretation_notes": [
                               "R3 and I3 are extensions: the contract names no clause for a generic-runtime-semantics dependence found by "
                               "rename-invariance (falsifier 3 mapped to reject) nor for generated-package load failures (mapped to inconclusive).",
                               "S2 also requires 0 string-literal domain-identity hits in scanned core code (stricter than 0 branches).",
                               "Requirement coverage is a registry-presence check: each carrier must exist in the IR, be a kernel kind and compile; "
                               "it does not prove the carrier's logic is right (see H17-H21).",
                               "Generated packages bind inert stub logic: the cases test generic validate/compile/load/dispatch, not domain logic."]})
    return out
