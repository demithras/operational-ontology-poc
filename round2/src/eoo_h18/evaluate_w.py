"""H18w evaluator (post-hoc weak H18, protocol/H18W_PREREG.json): the SAME six H18 evidence files -> verdict.json.

Every prereg clause is one named predicate with its numbers (S1, S1b, S2, S3, S4, S6, R, I, V). Numbers are recomputed from the raw
per-step rows (corpus.aggregate); a summary that disagrees with its rows is a problem. Missing/unreadable evidence never supports.
S5 and R2 of H18 are dropped by the prereg and are not evaluated here.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from eoo_engine import ENGINE_VERSION
from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import REPO, ROOT, sha_file

from . import corpus
from .run import HARNESS, HID, REQUIRED

WID = "H18w"
MIN_SEQUENCES = 3000
ENGINE_TAG = "r2-engine-v1.2"
ENGINE_PATHS = ("round2/src/eoo_engine", "round2/src/eoo_engine_git")
ORACLE_PATHS = ("round2/src/hdd/project_lifecycle_reference.py", "round2/oracles/h18")
TARGET_MUTANTS = ("M1_allow_post_freeze_threshold_edit", "M2_allow_verdict_without_evidence", "M3_detach_commit_provenance")
EVALUATOR_FILES = {"src/eoo_h18/evaluate_w.py", "scripts/evaluate_h18w.py"}  # frozen separately (evaluator_sha256), not run harness

SUPPORT = {"S1": f"0 illegal lifecycle transitions accepted across >= {MIN_SEQUENCES} unique generated sequences (any class; no refused op reached Git)",
           "S1b": "0 legal lifecycle transitions refused and 0 state mismatches: step-by-step agreement with the oracle in both directions",
           "S2": "100% of authoritative verdicts reproducible from frozen evidence/evaluator",
           "S3": "0 canonical ontology-only changes lacking a Git trace",
           "S4": "0 Project-domain branches in the generic Engine (static audit, planted known-positives found)",
           "S6": "all H18 target mutations detected (post-freeze threshold edit, verdict without evidence, detached commit provenance), controls clean"}
REJECT = {"R": "Any of S1/S1b/S3/S4 violated, or any core governance invariant bypassable (core-class illegal op accepted, hostile dogfood step accepted)"}
INCONCLUSIVE = {"I": f"fewer than {MIN_SEQUENCES} unique sequences, or any H18 hostile-edit class missing from the corpus"}
INVALID = {"V1": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
           "V2": "Evidence records disagree on commit / seed / corpus hash or do not name the current Engine version",
           "V3": f"The Engine (src/eoo_engine, src/eoo_engine_git) differs from tag {ENGINE_TAG}",
           "V4": "The lifecycle oracle (src/hdd/project_lifecycle_reference.py, oracles/h18) is changed",
           "V5": "Harness files were dirty at run time",
           "V6": "Harness self-check failed (mutation control not clean, harness error rows, harness files changed since the run) or the oracle is not independent"}


def paths_differing_from_tag(paths, tag: str = ENGINE_TAG, repo: Path = REPO) -> list[str]:
    """Paths whose working-tree content differs from ``tag`` (tracked diff + untracked files); read-only git. Unknown tag -> error entry."""
    def run(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
    if run("rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}").returncode != 0:
        return [f"tag {tag} not found"]
    d = run("diff", "--name-only", tag, "--", *paths)
    u = run("status", "--porcelain", "--untracked-files=all", "--", *paths)
    if d.returncode != 0 or u.returncode != 0:
        return [f"git failed: {(d.stderr or u.stderr).strip()[:100]}"]
    return sorted(set(d.stdout.split()) | {ln[3:] for ln in u.stdout.splitlines()})


def dirty_harness_files(rec: dict) -> list[str]:
    """Harness files (relative to round2/) the record's own dirty-path list covers, evaluator files excluded."""
    harness = [f for f in (rec.get("harness_sha256") or {}) if f not in EVALUATOR_FILES]
    out = []
    for p in rec.get("harness_dirty_paths") or []:
        p = p[len("round2/"):] if p.startswith("round2/") else None
        if p is None:
            continue
        out += [f for f in harness if f == p or (p.endswith("/") and f.startswith(p))]
    return sorted(set(out))


def evaluate(exp_dir, root: Path = ROOT, *, engine_diff=None, oracle_diff=None) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())[HID]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th, "minimum_sequences": MIN_SEQUENCES}
    sm, vr, gt, mu = (pay.get(f) for f in ("project-state-machine.json", "verdict-reproducibility.json", "git-traceability.json", "mutation-results.json"))
    if sm:
        agg = corpus.aggregate(sm["cases"])
        e, by = agg["eoo"], agg["eoo"]["by_class"]
        n.update(unique_cases=len({c["id"] for c in sm["cases"]}), steps=e["steps"], illegal_accepted=e["illegal_accepted"], illegal_accepted_core=e["illegal_accepted_core"],
                 legal_rejected=e["legal_rejected"], state_mismatches=e["state_mismatches"], exceptions=e["exceptions"], trace=agg["trace"],
                 evaluations=agg["evaluations"], class_counts=agg["class_counts"],
                 illegal_accepted_by_class={k: v["illegal_accepted"] for k, v in by.items() if v["illegal_accepted"]},
                 legal_rejected_by_class={k: v["legal_rejected"] for k, v in by.items() if v["legal_rejected"]},
                 supersede_self_steps=by.get("supersede_self", {}).get("n", 0), new_version_chain_steps=by.get("new_version_chain", {}).get("n", 0),
                 baseline_exceptions=agg["base"]["exceptions"], ir_version_in_evidence=next((r.get("ir_version") for r in recs.values()), None))
        if e["illegal_accepted"] != sm["eoo"]["illegal_accepted"] or e["steps"] != sm["eoo"]["steps"] or e["legal_rejected"] != sm["eoo"]["legal_rejected"]:
            problems.append("project-state-machine summary disagrees with its per-step rows")
        n["oracle_independent"] = sm["oracle"]["oracle_import_audit"]["independent"]
        n["engine_audit"] = {k: sm["engine_domain_audit"][k] for k in ("project_domain_branches", "domain_identity_branches")}
        n["engine_audit_scopes"] = {k: {x: v[x] for x in ("files_scanned", "string_constants_scanned", "branch_hits", "literal_hits")} for k, v in sm["engine_domain_audit"]["scopes"].items()}
        n["engine_audit_probes_found"] = {k: v["found"] for k, v in sm["engine_domain_audit"]["probes"].items()}
    if vr:
        a = vr["authoritative"]
        n["authoritative_reproducible"] = bool(a["reproducible"]) and a["derived_verdicts_in_temp_repo"][-1][1] == a["committed_verdict"]
        n["dogfood_hostile_accepted"] = [s["step"] for s in vr["dogfood_steps"] if s["accepted"] != s["expected_accept"]]
    if gt:
        cli = gt["dogfood_git_cli"]
        n["dogfood_cli"] = {k: cli[k] for k in ("fsck", "history_agrees", "accepted_actions", "accepted_with_matching_commit_trailers", "cli_commits_on_branch", "expected_commits")}
    if mu:
        by_id = {m["id"]: m for m in mu["mutants"]}
        tgt = [m for m in mu["mutants"] if m["target"]]
        n["target_mutants"] = {i: (by_id[i]["killed"] if i in by_id and by_id[i]["target"] else None) for i in TARGET_MUTANTS}
        n["mutation_target_total"], n["mutation_target_killed"] = len(tgt), sum(m["killed"] for m in tgt)
        n["mutation_target_survivors"] = [m["id"] for m in tgt if not m["killed"]]
        n["mutation_controls_clean"] = [mu["controls"]["clean"], mu["controls"]["clean_after"]]
        n["mutation_exceptions"] = sum(m["exceptions"] for m in mu["mutants"])

    def has(*k):
        return all(x in n for x in k)
    tr, cli = n.get("trace", {}), n.get("dogfood_cli", {})
    s1 = (n["illegal_accepted"] == 0 and tr["refused_with_commit"] == 0 and n["unique_cases"] >= MIN_SEQUENCES) if has("illegal_accepted", "unique_cases", "trace") else None
    s1b = (n["legal_rejected"] == 0 and n["state_mismatches"] == 0 and n["steps"] > 0) if has("legal_rejected", "state_mismatches") else None
    s2 = (n["authoritative_reproducible"] and n["evaluations"]["verdict_matches_oracle"] == n["evaluations"]["accepted_evaluations"] > 0) if has("authoritative_reproducible", "evaluations") else None
    s3 = (tr["ontology_only_writes"] <= th["max_canonical_changes_without_git"] and tr["non_git_effects"] == 0 and tr["commits_without_acceptance"] == 0
          and tr["accepted_actions"] > 0 and tr["trace_ok"] == tr["accepted_actions"] == tr["one_commit_each"] and cli.get("fsck") is True and cli.get("history_agrees") is True
          and cli.get("accepted_with_matching_commit_trailers") == cli.get("accepted_actions") and cli.get("cli_commits_on_branch") == cli.get("expected_commits")) if has("trace", "dogfood_cli") else None
    s4 = (n["engine_audit"]["project_domain_branches"] == 0 and n["engine_audit"]["domain_identity_branches"] == 0 and all(n["engine_audit_probes_found"].values())
          and sum(v["string_constants_scanned"] for v in n["engine_audit_scopes"].values()) > 1000) if has("engine_audit") else None
    s6 = (all(v is True for v in n["target_mutants"].values()) and not n["mutation_target_survivors"] and all(n["mutation_controls_clean"])) if has("target_mutants") else None
    s1_violated = (n["illegal_accepted"] > 0 or tr["refused_with_commit"] > 0) if has("illegal_accepted", "trace") else None  # an OBSERVED violation; "< 3000 sequences" is not one (-> I)
    r = (s1_violated is True or s1b is False or s3 is False or s4 is False or n["illegal_accepted_core"] > th["max_illegal_lifecycle_transitions"]
         or bool(n.get("dogfood_hostile_accepted"))) if has("illegal_accepted_core") and s1_violated is not None and s1b is not None else None
    i = (n["unique_cases"] < MIN_SEQUENCES or any(c == 0 for c in n["class_counts"].values()) or n["steps"] <= 0) if has("unique_cases", "class_counts") else None
    ed = engine_diff(ENGINE_PATHS) if engine_diff else paths_differing_from_tag(ENGINE_PATHS)
    od = oracle_diff(ORACLE_PATHS) if oracle_diff else paths_differing_from_tag(ORACLE_PATHS)
    dirty = {f: dirty_harness_files(rec) for f, rec in recs.items() if dirty_harness_files(rec)}
    stale = [f for f, h in (recs[REQUIRED[0]].get("harness_sha256") or {}).items() if f not in EVALUATOR_FILES and (root / f).exists() and sha_file(root / f) != h] if REQUIRED[0] in recs else []
    selfcheck = []
    if mu is not None and not all(n["mutation_controls_clean"]):
        selfcheck.append("mutation control not clean")
    if has("exceptions") and (n["exceptions"] or n["baseline_exceptions"] or n.get("mutation_exceptions")):
        selfcheck.append(f"harness error rows: eoo={n['exceptions']} baseline={n['baseline_exceptions']} mutation={n.get('mutation_exceptions', 0)}")
    if stale:
        selfcheck.append(f"harness files changed since the run: {stale[:5]}")
    if sm and not n["oracle_independent"]:
        selfcheck.append("oracle not independent")
    engine_bad = [f for f, rec in recs.items() if rec.get("engine_version") != ENGINE_VERSION]
    n.update(engine_paths_differing_from_tag=ed, oracle_paths_differing_from_tag=od, harness_dirty_files_at_run=dirty, harness_self_check=selfcheck)
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S1b": s1b, "S2": s2, "S3": s3, "S4": s4, "S6": s6}), "reject_if": sc.rows(REJECT, {"R": r}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I": i}),
            "invalid_if": sc.rows(INVALID, {"V1": bool(wrong), "V2": len(ident) > 1 or bool(engine_bad), "V3": bool(ed), "V4": bool(od), "V5": bool(dirty), "V6": bool(selfcheck)})}
    valid = not wrong and len(ident) <= 1 and not engine_bad and not ed and not od and not dirty and not selfcheck
    return sc.finish(WID, ident[0][3] if ident else None, protocol_valid=valid, complete=not problems, sample_sufficient=(i is False),
                     reject_hit=r is True, support_hit=all(x is True for x in (s1, s1b, s2, s3, s4, s6)), predicates=pred, numbers=n, problems=problems,
                     extra={"engine_version": ENGINE_VERSION, "post_hoc": True, "protocol": {"freeze_sha256": freeze_hash()},
                            "protocol_mismatches": {"records_with_wrong_hashes": wrong, "disagreeing_provenance": len(ident) > 1, "records_not_naming_current_engine_version": engine_bad},
                            "evidence_payload_hashes": {f: x["payload_hash"] for f, x in sorted(recs.items())}, "evaluator_sha256": sha_file(Path(__file__)),
                            "interpretation_notes": ["H18w is POST-HOC (formulated after exp-h18-001 was known): lower evidential weight than a preregistered hypothesis (H18W_PREREG.json).",
                                                     "S1 counts illegal ops accepted in EVERY class (core and extension); S1b adds legal_rejected and state mismatches (strictly stronger than H18).",
                                                     "S5/R2 of H18 are dropped by the prereg and not evaluated; the baseline/metrics evidence files are still required (same run).",
                                                     "V5 reads the dirty paths recorded in the evidence against the harness files hashed in it (evaluator files excluded)."]})
