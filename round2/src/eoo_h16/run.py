"""Frozen H16 experiment run: builds the six evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import json
from pathlib import Path

from eoo_engine.registry import load_model
from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, canon, sha_file, sha_text

from . import detectors
from .audit import domain_files
from .coverage import requirement_coverage
from .gen import KINDS
from .kernel import live_snapshot, rev_snapshot
from .loadcheck import rename_invariant
from .mixed import generate
from .mutation_run import run_mutations

HID = "H16"
REQUIRED = ["kernel-before.json", "kernel-after.json", "core-diff.json", "domain-branch-audit.json",
            "mixed-domain-generated.json", "mutation-results.json"]
BEFORE_REV = "r2-engine-core"  # tag 0aad1ff: the Engine as first committed, before any domain was bound
AFTER_REV = "HEAD"
HARNESS = [*sorted((ROOT / "src/eoo_h16").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")),
           ROOT / "scripts/run_h16.py", ROOT / "scripts/evaluate_h16.py"]


def domain_usage(kernel_kinds: list, schema_fields: list) -> dict:
    out = {}
    for name, f in domain_files().items():
        pkg = json.loads(Path(f).read_text())
        model = load_model(pkg)  # through DISPATCH_TABLE
        arrays = {k: len(v) for k, v in pkg.items() if isinstance(v, list) and k != "imports"}
        out[name] = {"file": Path(f).relative_to(ROOT).as_posix(), "sha256": sha_file(f), "package_id": pkg["package_id"],
                     "domain_id": pkg.get("domain_id"), "version": pkg["version"], "resource_arrays": arrays,
                     "top_level_keys_not_in_schema": sorted(set(pkg) - set(schema_fields)),
                     "arrays_not_kernel_kinds": sorted(set(arrays) - set(kernel_kinds)),
                     "compiled_sizes": {k: len(model.kinds.get(k, {})) for k in KINDS},
                     "engine_compiled_every_resource": all(len(model.kinds.get(k, {})) == arrays.get(k, 0) for k in KINDS)}
    return out


KNOWN_FINDINGS = [
    {"id": "F1", "source": "commit c9443a0 message; tests/domains/test_manufacturing_logic.py",
     "finding": "manufacturing expedite_purchase_order and reschedule_work_order are unauthorizable on the frozen IR (their "
                "authority_refs name rules whose capability is action:transfer_inventory; the IR has no object binding)",
     "kernel_impact": "none: a declaration-level (domain IR) gap, no new kernel kind or Engine branch was needed to observe it"},
    {"id": "F2", "source": "commit c9443a0 message", "finding": "one project policy is not referenced by any action "
     "(conflicting_change_denied_with_conflict); reported as unwired_policy_or_authority_carriers", "kernel_impact": "none"},
    {"id": "F3", "source": "commit c9443a0 message; domains/project/CHANGES_v2.md",
     "finding": "project v1 attach_evidence never created the SUPPORTS_OR_REFUTES link evidence_count reads; fixed in v2 by an ordinary "
                "action-effect declaration before any H16-H22 evidence", "kernel_impact": "none"},
    {"id": "F4", "source": "commit c9443a0 message", "finding": "high-priority protection is modelled as a deny policy over principal "
     "relations; three deny rules carry never-requested capabilities", "kernel_impact": "none"}]


def baseline_contextual() -> dict:
    ir = json.loads((ROOT / "domains/project/ir.v2.json").read_text())
    n = {k: len(ir[k]) for k in KINDS}
    loc = sum(1 for p in sorted((ROOT / "domains/project").rglob("*.py")) for ln in p.read_text().splitlines()
              if ln.strip() and not ln.strip().startswith("#"))
    return {"status": "CONTEXTUAL ESTIMATE, not measured, not a support condition",
            "ontology_path": {"new_kernel_kinds": 0, "new_engine_core_files": 0, "new_declared_resources": sum(n.values()),
                              "project_domain_python_loc_non_blank": loc},
            "conventional_typed_schema_plus_plugin_registry_would_need": {
                "new_tables": n["object_types"] + n["link_types"], "new_model_classes": n["object_types"] + n["interfaces"],
                "new_rule_or_action_handlers": n["functions"] + n["actions"] + n["policies"] + n["authority_rules"] + n["constraints"],
                "new_observation_adapters": n["observation_types"],
                "assumptions": "one table per object type and per link type, one class per object type and interface, one "
                               "plugin handler per function/action/policy/authority rule/constraint, one adapter per observation type"},
            "reading": "Both approaches add Domain 2 declarations/logic; neither is shown to need a different kernel. The "
                       "ontology path's bounded-kernel property is the 0 new kinds measured above; this table does not show "
                       "that a conventional framework is worse."}


def file_diff(a: dict, b: dict) -> dict:
    return {"changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]), "added": sorted(set(b) - set(a)),
            "removed": sorted(set(a) - set(b))}


def build(seed: int, n: int) -> tuple[dict, dict]:
    before, after = rev_snapshot(BEFORE_REV), rev_snapshot(AFTER_REV)
    live = live_snapshot()
    kk = after["kernel_resource_kinds"]
    usage = domain_usage(kk, after["ir_schema"]["package_fields"])
    diff = detectors.kernel_diff(before, after)
    wt = {"live_dispatch_equals_head": live["dispatch"]["handlers"] == after["dispatch"]["handlers"],
          "live_schema_sha_equals_head": live["ir_schema"]["sha256"] == after["ir_schema"]["sha256"],
          "engine_core_working_tree_equals_head": {p.relative_to(ROOT / "src").as_posix(): sha_file(p) for p in
                                                   sorted((ROOT / "src/eoo_engine").glob("*.py"))} == after["engine_core_files"]}
    fz = {f["path"]: f["sha256"] for f in json.loads((ROOT / "protocol/FREEZE.json").read_text())["files"]}
    project = json.loads((ROOT / "domains/project/ir.v2.json").read_text())
    cov = requirement_coverage(project, kk, load_model(project))
    gen = generate(seed, n, max_attempt_factor=6)
    audit = detectors.audit_sources(include_info=True)
    audit["rename_invariance_real_domains"] = {k: rename_invariant(json.loads(Path(f).read_text()))["invariant"]
                                               for k, f in domain_files().items()}
    mut = run_mutations(before)
    core = {**diff, "engine_core_files_diff": file_diff(before["engine_core_files"], after["engine_core_files"]),
            "eoo_ir_files_diff": file_diff(before["eoo_ir_files"], after["eoo_ir_files"]),
            "schema_sha_matches_freeze_entry": after["ir_schema_blob_sha256"] == fz.get("ontology/ir.schema.json"),
            "proposed_new_primitives_for_a_new_hypothesis_version": diff["new_kernel_primitive_kinds"],
            "domain2_requirement_coverage": cov, "baseline_contextual": baseline_contextual(),
            "working_tree": wt, "known_findings_carried_not_fixed": KNOWN_FINDINGS,
            "project_contract_version_used": "domains/project/ir.v2.json (v1 ir.json is H15's frozen Gate-0 input; both compile, see kernel-after)",
            "domain_usage_note": "per-domain resource kinds used are in kernel-after.json"}
    payloads = {
        "kernel-before.json": {"snapshot": before, "prereg_kernel_snapshot_source": "protocol/ENGINE_PREREG.json at the before commit"},
        "kernel-after.json": {"snapshot": after, "domain_usage": usage, "working_tree": wt},
        "core-diff.json": core, "domain-branch-audit.json": audit, "mixed-domain-generated.json": gen,
        "mutation-results.json": mut}
    return payloads, {"corpus_hash": gen["corpus_hash"], "unique": gen["unique_cases"]}


def run(seed: int, n: int, out_root: Path, exp_id: str) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads, info = build(seed, n)
        p = prov.provenance(pre, exp_id, HID, seed, info["corpus_hash"], HARNESS,
                            kernel_before_commit=payloads["kernel-before.json"]["snapshot"]["git_commit"],
                            kernel_after_commit=payloads["kernel-after.json"]["snapshot"]["git_commit"])
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads[fn]))
    return info
