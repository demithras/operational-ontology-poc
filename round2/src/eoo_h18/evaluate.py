"""Frozen H18 evaluator: evidence directory -> verdict.json. Every contract clause is one named predicate with numbers.

Numbers are RECOMPUTED from raw rows (per-step corpus rows, mutant rows, LOC assignments), never copied from a summary; a
summary that disagrees with its raw data is a problem and blocks SUPPORTED. Missing/unreadable evidence never supports.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_engine import ENGINE_VERSION
from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, sha_file

from . import corpus
from .run import HARNESS, HID, REQUIRED

SUPPORT = {"S1": "0 illegal lifecycle transitions accepted across the generated corpus (>= the contract minimum of unique sequences)",
           "S2": "100% authoritative verdicts reproducible from frozen evidence/evaluator",
           "S3": "0 canonical ontology-only changes lacking Git trace",
           "S4": "0 Project-domain branches in the generic Engine (static audit incl. the Git store, with planted known-positives found)",
           "S5": ">= 25% lower bespoke surface than the equally strong file-only baseline in >= 1 task class with no correctness loss",
           "S6": "All target mutations killed, controls clean (frozen required_mutation_kill_rate)"}
REJECT = {"R1": "A core governance invariant (docs/04 hard rule or lifecycle order) can be bypassed",
          "R2": "All preregistered task classes show parity/worse bespoke change surface while EOO adds recurring complexity",
          "R3": "Project lifecycle enforcement requires a bespoke (domain-identity) branch in the generic Engine"}
INCONCLUSIVE = {"I1": "The baseline is not implemented to equivalent invariant strength (it disagrees with the oracle) or a task class has no correct baseline",
                "I2": "The task corpus is incomplete (fewer unique sequences than the minimum, or a required hostile/lifecycle class never generated)"}
INVALID = {"V1": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
           "V2": "Evidence records disagree on commit / seed / corpus hash or do not name the current Engine version",
           "V3": "Harness self-check failed (mutation control not clean, harness error rows, harness files changed since the run)",
           "V4": "Project Ontology graded its own hypothesis: the independent oracle imports runtime code or was not consulted on every step"}


def _ratio(per: dict) -> dict:
    out = {}
    for c, v in per.items():
        e, b = v["eoo"]["total"], v["baseline"]["total"]
        out[c] = {"eoo": e, "baseline": b, "reduction": round(1 - e / b, 4) if b else None, "correct_eoo": v["correctness"]["eoo"],
                  "correct_baseline": v["correctness"]["baseline"]}
    return out


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())[HID]
    min_n = json.loads((root / "hypotheses/h18/contract.json").read_text())["experiment"]["minimum_runs"]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th, "minimum_runs": min_n}
    P = pay.get
    sm, vr, gt, bc, bm, mu = (P(f) for f in REQUIRED)
    if sm:
        cases = sm["cases"]
        agg = corpus.aggregate(cases)
        n.update(unique_cases=len({c["id"] for c in cases}), steps=agg["eoo"]["steps"], eoo_illegal_accepted=agg["eoo"]["illegal_accepted"],
                 eoo_illegal_accepted_core=agg["eoo"]["illegal_accepted_core"], eoo_legal_rejected=agg["eoo"]["legal_rejected"],
                 eoo_state_mismatches=agg["eoo"]["state_mismatches"], eoo_exceptions=agg["eoo"]["exceptions"], baseline_illegal_accepted=agg["base"]["illegal_accepted"],
                 baseline_legal_rejected=agg["base"]["legal_rejected"], baseline_state_mismatches=agg["base"]["state_mismatches"], baseline_exceptions=agg["base"]["exceptions"],
                 class_counts=agg["class_counts"], trace=agg["trace"], evaluations=agg["evaluations"],
                 illegal_accepted_by_class={k: v["illegal_accepted"] for k, v in agg["eoo"]["by_class"].items() if v["illegal_accepted"]},
                 legal_rejected_by_class={k: v["legal_rejected"] for k, v in agg["eoo"]["by_class"].items() if v["legal_rejected"]},
                 baseline_divergent_classes={k: v["illegal_accepted"] + v["legal_rejected"] for k, v in agg["base"]["by_class"].items() if v["illegal_accepted"] or v["legal_rejected"]})
        if agg["eoo"]["illegal_accepted"] != sm["eoo"]["illegal_accepted"] or agg["eoo"]["steps"] != sm["eoo"]["steps"]:
            problems.append("project-state-machine summary disagrees with its per-step rows")
        n["oracle_independent"], n["oracle_imports"] = sm["oracle"]["oracle_import_audit"]["independent"], sm["oracle"]["oracle_import_audit"]["files"]
        n["engine_audit"] = {k: sm["engine_domain_audit"][k] for k in ("project_domain_branches", "domain_identity_branches")}
        n["engine_audit_scopes"] = {k: {x: v[x] for x in ("files_scanned", "string_constants_scanned", "branch_hits", "literal_hits")} for k, v in sm["engine_domain_audit"]["scopes"].items()}
        n["engine_audit_probes_found"] = {k: v["found"] for k, v in sm["engine_domain_audit"]["probes"].items()}
        n["eoo_only_battery"] = sm["eoo_only_battery"]["checks"]
        n["domain_blind_store_roundtrip"] = sm["domain_blind_store_check"]["roundtrip_identity"]
        n["engine_version_in_evidence"] = sm["engine_version"]
    if vr:
        a = vr["authoritative"]
        n["authoritative_reproducible"] = bool(a["reproducible"]) and a["derived_verdicts_in_temp_repo"][-1][1] == a["committed_verdict"]
        n["dogfood_hostile_accepted"] = [s["step"] for s in vr["dogfood_steps"] if s["accepted"] != s["expected_accept"]]
        n["dogfood_phase"] = a["final_phase"]
    if gt:
        cli = gt["dogfood_git_cli"]
        n["dogfood_cli"] = {k: cli[k] for k in ("fsck", "history_agrees", "accepted_actions", "accepted_with_matching_commit_trailers", "cli_commits_on_branch", "expected_commits")}
    if bc:
        n["variants_disagree_on_steps"], n["tc2_correct"], n["tc3_correct"] = bc["variants_disagree_on_steps"], bc["tc2"]["baseline_correct"], bc["tc3"]["baseline_correct"]
    if bm:
        n["metrics"] = _ratio(bm["per_class"])
        n["recurring_complexity_loc"] = {k: bm["recurring_complexity_loc"][k] for k in ("eoo", "baseline")}
        n["python_unassigned"] = bm["python_unassigned_lines"]
        n["excluded_not_counted"] = bm["excluded_not_counted"]
        n["sensitivity_without_mandatory_extras"] = {c: v["eoo_reduction_without_extras"] for c, v in bm["per_class"].items()}
    if mu:
        tgt = [m for m in mu["mutants"] if m["target"]]
        n["mutation_target_total"], n["mutation_target_killed"] = len(tgt), sum(m["killed"] for m in tgt)
        n["mutation_kill_rate"] = (n["mutation_target_killed"] / len(tgt)) if tgt else 0.0
        n["mutation_survivors"] = [m["id"] for m in mu["mutants"] if not m["killed"]]
        n["mutation_classes_present"] = sorted({m["class"] for m in tgt})
        n["mutation_controls_clean"] = [mu["controls"]["clean"], mu["controls"]["clean_after"]]
        n["mutation_exceptions"] = sum(m["exceptions"] for m in mu["mutants"])

    def has(*k):
        return all(x in n for x in k)
    tr = n.get("trace", {})
    cli = n.get("dogfood_cli", {})
    s1 = (n["eoo_illegal_accepted"] == 0 and tr["refused_with_commit"] == 0 and n["unique_cases"] >= min_n) if has("eoo_illegal_accepted", "unique_cases") else None
    s2 = (n["authoritative_reproducible"] and n["evaluations"]["verdict_matches_oracle"] == n["evaluations"]["accepted_evaluations"] > 0) if has("authoritative_reproducible", "evaluations") else None
    s3 = (tr["ontology_only_writes"] <= th["max_canonical_changes_without_git"] and tr["non_git_effects"] == 0 and tr["commits_without_acceptance"] == 0
          and tr["accepted_actions"] > 0 and tr["trace_ok"] == tr["accepted_actions"] == tr["one_commit_each"] and cli.get("fsck") is True and cli.get("history_agrees") is True
          and cli.get("accepted_with_matching_commit_trailers") == cli.get("accepted_actions") and cli.get("cli_commits_on_branch") == cli.get("expected_commits")) if has("trace", "dogfood_cli") else None
    s4 = (n["engine_audit"]["project_domain_branches"] == 0 and n["engine_audit"]["domain_identity_branches"] == 0 and all(n["engine_audit_probes_found"].values())
          and sum(v["string_constants_scanned"] for v in n["engine_audit_scopes"].values()) > 1000) if has("engine_audit") else None
    s5 = (any(v["reduction"] is not None and v["reduction"] >= th["min_bespoke_surface_reduction_in_one_task_class"] and (v["correct_eoo"] or not v["correct_baseline"])
              for v in n["metrics"].values())) if has("metrics") else None
    s6 = (n["mutation_kill_rate"] >= th["required_mutation_kill_rate"] and not n["mutation_survivors"] and all(n["mutation_controls_clean"])
          and {"lifecycle_rule", "git_traceability"} <= set(n["mutation_classes_present"])) if has("mutation_kill_rate") else None
    r1 = (n["eoo_illegal_accepted_core"] > th["max_illegal_lifecycle_transitions"] or bool(n.get("dogfood_hostile_accepted"))) if has("eoo_illegal_accepted_core") else None
    r2 = (all(v["reduction"] is not None and v["reduction"] <= 0 for v in n["metrics"].values()) and len(n["metrics"]) == 3
          and n["recurring_complexity_loc"]["eoo"] > n["recurring_complexity_loc"]["baseline"]) if has("metrics", "recurring_complexity_loc") else None
    r3 = (n["engine_audit"]["project_domain_branches"] > 0) if has("engine_audit") else None
    i1 = (n["baseline_illegal_accepted"] + n["baseline_legal_rejected"] + n["baseline_state_mismatches"] > 0 or not n["tc2_correct"] or not n["tc3_correct"]
          or not all(v["correct_baseline"] for v in n["metrics"].values())) if has("baseline_illegal_accepted", "tc2_correct", "metrics") else None
    i2 = (n["unique_cases"] < min_n or any(c == 0 for c in n["class_counts"].values()) or n["steps"] <= 0) if has("unique_cases", "class_counts") else None
    ours = {"src/eoo_h18/evaluate.py", "scripts/evaluate_h18.py"}  # the evaluator is frozen separately (evaluator_sha256), not part of the run harness
    stale = [f for f, h in (recs[REQUIRED[0]].get("harness_sha256") or {}).items() if f not in ours and (root / f).exists() and sha_file(root / f) != h] if REQUIRED[0] in recs else []
    v3 = []
    if mu is not None and not all(n["mutation_controls_clean"]):
        v3.append("mutation control not clean")
    if has("eoo_exceptions") and (n["eoo_exceptions"] or n["baseline_exceptions"] or n.get("mutation_exceptions")):
        v3.append(f"harness error rows: eoo={n['eoo_exceptions']} baseline={n['baseline_exceptions']} mutation={n.get('mutation_exceptions', 0)}")
    if stale:
        v3.append(f"harness files changed since the run: {stale[:5]}")
    v2x = [f for f, r in recs.items() if r.get("engine_version") != ENGINE_VERSION]
    v4 = bool(sm) and (not n["oracle_independent"] or n["steps"] <= 0)
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6}), "reject_if": sc.rows(REJECT, {"R1": r1, "R2": r2, "R3": r3}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1, "I2": i2}),
            "invalid_if": sc.rows(INVALID, {"V1": bool(wrong), "V2": len(ident) > 1 or bool(v2x), "V3": bool(v3), "V4": v4})}
    out = sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not wrong and len(ident) <= 1 and not v2x and not v3 and not v4,
                    complete=not problems, sample_sufficient=(i1 is False and i2 is False),
                    reject_hit=any(x is True for x in (r1, r2, r3)), support_hit=all(x is True for x in (s1, s2, s3, s4, s5, s6)), predicates=pred, numbers=n, problems=problems,
                    extra={"engine_version": ENGINE_VERSION, "protocol_mismatches": {"records_with_wrong_hashes": wrong, "disagreeing_provenance": len(ident) > 1,
                           "records_not_naming_current_engine_version": v2x, "harness_self_check": v3}, "protocol": {"freeze_sha256": freeze_hash()},
                           "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())}, "evaluator_sha256": sha_file(Path(__file__)),
                           "harness_dirty_at_run": {f: r.get("harness_dirty") for f, r in recs.items()},
                           "interpretation_notes": [
                               "R1 counts only CORE classes (docs/04 hard rules + lifecycle order: " + ", ".join(corpus.CORE_CLASSES) + "); an illegal op accepted in an EXTENSION class "
                               "(supersede_self, new_version_overwrite, decision_blank_rationale) blocks S1 but is not by itself a reject.",
                               "R2 reads 'parity/worse' as EOO total >= baseline total in every class; headline totals count mandatory EOO surface (authority rules, outcome predicates) "
                               "conservatively; the sensitivity without them is in numbers.sensitivity_without_mandatory_extras.",
                               "R3 maps falsifier 1 to the static audit; the contract names no reject clause for it.",
                               "S6 is the thresholds.json required_mutation_kill_rate; the contract support_if does not list it.",
                               "legal ops the Engine refused (legal_rejected) are reported, not graded: the contract has no clause for false refusals."]})
    return out
