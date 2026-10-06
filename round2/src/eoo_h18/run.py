"""Frozen H18 experiment run: builds the six evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from domains._pack import load_ir
from domains.project.logic.freeze import git_blob_reader
from eoo_engine import ENGINE_VERSION
from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, head_commit

from . import audit, corpus, dogfood, extras, manifest, metrics, mutation_run, tc_run
from .rig import EooRig

HID = "H18"
REQUIRED = ["project-state-machine.json", "verdict-reproducibility.json", "git-traceability.json", "baseline-comparison.json",
            "bespoke-change-metrics.json", "mutation-results.json"]
HARNESS = [*sorted((ROOT / "src/eoo_h18").glob("*.py")), *sorted((ROOT / "src/eoo_h18").glob("*.json")), *sorted((ROOT / "src/eoo_engine_git").glob("*.py")),
           *sorted((ROOT / "src/eoo_exp").glob("*.py")), *sorted((ROOT / "oracles/h18").glob("*.py")),
           *sorted((ROOT / "baselines/h18_fileonly").glob("*.py")), *sorted((ROOT / "baselines/h18_fileonly/schemas").glob("*.json")),
           ROOT / "domains/project/pack.py", ROOT / "domains/_pack.py", *sorted((ROOT / "domains/project/logic").glob("*.py")),
           ROOT / "domains/project/ir.v2.json", ROOT / "domains/project/ir.v3.json", ROOT / "scripts/run_h18.py", ROOT / "scripts/evaluate_h18.py"]
EOO_ONLY = ["identity (unknown principal denied)", "authority rules (role-based allow / default deny)", "idempotency keys (replay writes nothing twice)",
            "observed-outcome reconciliation (Git observation checked against the intended row)", "refusal of direct canonical writes without a live grant",
            "typed integrity rules from the IR on every Git row (undeclared property, bad type, immutable change, cardinality)"]
BASELINE_ONLY = ["no identity, authority or idempotency: any committer can edit any file; CI sees only the diff",
                 "an empty diff cannot be rejected by CI (guards live in the change helpers)", "no outcome reconciliation: a merged commit is taken as done"]


def head_sha() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def build(seed: int, n: int, mut_n: int, log=print, ir_version=None) -> tuple[dict, dict]:
    sha = head_sha()
    reader = git_blob_reader(sha)
    rig = EooRig(tempfile.mkdtemp(prefix="eoo-h18-run-"), reader=reader, ir_version=ir_version)
    cases, ginfo = corpus.generate(rig, seed, n)
    log(f"[run] corpus {ginfo}")
    results = corpus.execute(rig, cases, log)
    agg = corpus.aggregate(results)
    log("[run] corpus done: " + str({k: agg['eoo'][k] for k in ('steps', 'illegal_accepted', 'legal_rejected', 'state_mismatches')}))
    battery = extras.eoo_only_battery(rig)
    dog = dogfood.run_dogfood(reader, ir_version=ir_version)
    trig = tc_run.tc_rig(reader, ir_version=ir_version)
    tc2, tc3 = tc_run.run_tc2(trig, reader), tc_run.run_tc3(trig, reader)
    corr = {"TC1": {"eoo": agg["eoo"]["illegal_accepted"] == 0 and agg["eoo"]["legal_rejected"] == 0 and agg["eoo"]["state_mismatches"] == 0,
                    "baseline": agg["base"]["illegal_accepted"] == 0 and agg["base"]["legal_rejected"] == 0 and agg["base"]["state_mismatches"] == 0,
                    "eoo_agreement": agg["eoo"]["agreement"], "baseline_agreement": agg["base"]["agreement"]},
            "TC2": {"eoo": all(tc2["eoo_correct"].values()), "baseline": all(tc2["baseline_correct"].values())},
            "TC3": {"eoo": tc3["eoo_correct"], "baseline": tc3["baseline_correct"]}}
    log("[run] metrics")
    met = metrics.measure(corr)
    log("[run] mutations")
    mut = mutation_run.run_mutations(reader, n=mut_n, ir_version=ir_version)
    eng = audit.engine_audit()
    sm_payload = {"engine_version": ENGINE_VERSION, "real_repo_pinned_commit": sha, "corpus": ginfo, "oracle": {
        "phase_legality": "src/hdd/project_lifecycle_reference.py (HypothesisState transitions)", "world_model": "oracles/h18/world.py",
        "oracle_import_audit": extras.oracle_imports(), "note": "Project logic itself imports the reference model for phase order (domains/project/logic/lifecycle.py): phase-order "
                                                                 "agreement is therefore structural; the differential also covers completeness, evidence pinning, derivation, supersession, versions and orphans."},
        "eoo": agg["eoo"], "evaluations": agg["evaluations"], "class_counts": agg["class_counts"], "core_classes": list(corpus.CORE_CLASSES),
        "eoo_only_battery": battery, "engine_domain_audit": eng, "domain_blind_store_check": extras.domain_blind_store(),
        "cases": results}
    vr = {"engine_version": ENGINE_VERSION, "authoritative": {"hypothesis": "H15", "experiment": dogfood.EXP, "committed_verdict": dog["committed_verdict"],
                                                              "derived_verdicts_in_temp_repo": dog["derived_verdicts"], "reproducible": dog["reproducible"],
                                                              "freeze_hash": dog["freeze_hash"], "final_phase": dog["phase_final"],
                                                              "evaluator": "eoo_h15.evaluate (real, un-memoised), over the committed exp-h15-002 evidence"},
          "dogfood_steps": dog["steps"], "corpus_evaluations": agg["evaluations"],
          "population": {"authoritative_total": 1, "authoritative_reproducible": int(dog["reproducible"]),
                         "corpus_total": agg["evaluations"]["accepted_evaluations"], "corpus_reproducible": agg["evaluations"]["verdict_matches_oracle"]}}
    gt = {"engine_version": ENGINE_VERSION, "corpus": agg["trace"], "dogfood_git_cli": dog["git_cli"], "dogfood_repo_commits": len(dog["steps"]),
          "mutation_provenance": [m for m in mut["mutants"] if m["id"].startswith("M3")],
          "definition": "canonical change = an accepted Action. Traced = exactly one new commit on the case branch whose message (the Engine provenance envelope, Engine v1.2) names the Engine execution, action and engine version, and whose adapter response recorded by the Engine names that commit and the base commit; "
                        "ontology-only write = the Engine's own store changed, a non-git effect ran, or a commit appeared without an accepted Action."}
    bc = {"engine_version": ENGINE_VERSION, "baseline": "round2/baselines/h18_fileonly (Git + JSON files + JSON Schema + Python CI gate)", "same_corpus_cases": ginfo["unique_cases"],
          "baseline_result": {k: agg["base"][k] for k in ("steps", "accepted", "illegal_accepted", "legal_rejected", "state_mismatches", "exceptions", "agreement", "illegal_accepted_core",
                                                          "divergence_total", "divergence_examples")},
          "eoo_result": {k: agg["eoo"][k] for k in ("steps", "accepted", "illegal_accepted", "legal_rejected", "state_mismatches", "exceptions", "agreement", "illegal_accepted_core",
                                                    "divergence_total", "divergence_examples")},
          "per_class": {"eoo": agg["eoo"]["by_class"], "baseline": agg["base"]["by_class"]}, "variants_disagree_on_steps": agg["variants_disagree"],
          "equal_invariant_strength": {"verified_against": ["src/hdd/project_lifecycle_reference.py", "oracles/h18/world.py"], "same_generated_sequences": True,
                                       "baseline_matches_oracle_on_every_step": agg["base"]["illegal_accepted"] == 0 and agg["base"]["legal_rejected"] == 0 and agg["base"]["state_mismatches"] == 0},
          "eoo_capabilities_without_baseline_counterpart": EOO_ONLY, "baseline_properties": BASELINE_ONLY, "tc2": tc2, "tc3": tc3}
    bm = {"engine_version": ENGINE_VERSION, **met, "tc2": {k: tc2[k] for k in ("eoo_correct", "baseline_correct")}, "tc3": tc3,
          "decision_rule": "support needs total <= 0.75 x baseline total in >= 1 class with no correctness loss (ENGINE_PREREG H18)"}
    return ({"project-state-machine.json": sm_payload, "verdict-reproducibility.json": vr, "git-traceability.json": gt, "baseline-comparison.json": bc,
             "bespoke-change-metrics.json": bm, "mutation-results.json": {"engine_version": ENGINE_VERSION, **mut}}, ginfo)


def run(seed: int, n: int, out_root: Path, exp_id: str, mut_n: int = 200, log=print, ir_version=None) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads, info = build(seed, n, mut_n, log, ir_version)
        p = prov.provenance(pre, exp_id, HID, seed, info["corpus_hash"], HARNESS, engine_version=ENGINE_VERSION, real_repo_pinned_commit=head_sha(),
                        ir_version=load_ir("project", ir_version)["version"])
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads[fn]))
    return info
