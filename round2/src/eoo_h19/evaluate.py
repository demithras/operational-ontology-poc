"""H19 evaluator: the five evidence files -> verdict.json. Every contract clause is one named predicate with its numbers.

support_if:      S1 rebuild hash equality, S2 no canonical ontology-only write, S3 no silent lost update, S4 bindings pinned, S5 target mutants detected
                 (S3b, stricter than the contract and reported separately: every write outcome equals the oracle's, conflicts replay, refusals leave Git alone)
reject_if:       R  any split-brain / nondeterministic rebuild / silent lost update / history rebinding OBSERVED
inconclusive_if: I  the concurrency corpus is smaller than the contract minimum or lacks a stale-base / conflicting-change (or any registered) class
invalid_if:      V1..V6 (V4 = the oracle is not independent of runtime storage)
Numbers are recomputed from the per-write / per-step rows; a summary that disagrees with its rows is a problem. Missing evidence never supports.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_engine import ENGINE_VERSION
from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import REPO, ROOT, sha_file
from eoo_h18.evaluate_w import dirty_harness_files, paths_differing_from_tag

from . import audit, independence, storelevel
from .run import HID, REQUIRED

ENGINE_TAG = "r2-engine-v1.2"
ENGINE_PATHS = ("round2/src/eoo_engine", "round2/src/eoo_engine_git")
MIN_CLASS = 50
TARGETS = ("M1_timestamp_dependent_projection", "M2_missing_base_version_check", "M3_history_rebinding")
EVALUATOR_FILES = {"src/eoo_h19/evaluate.py", "scripts/evaluate_h19.py"}
CLASSES = ("compatible_concurrent", "conflicting_concurrent", "stale_base", "rebuild_same_commit", "historical_binding_after_change")

SUPPORT = {"S1": "100% rebuild hash equality for identical Git commits (>= 2 fresh rebuilds each, every commit of every generated history, store and Engine histories)",
           "S2": "0 canonical ontology-only writes (Engine-level audit from raw Git; every accepted Action = exactly one traced commit; projection == Git)",
           "S3": "0 silent lost updates in the generated concurrency corpus (raw-Git definition) and no stale/conflicting write accepted that the oracle refuses",
           "S3b": "(stricter than the contract) every write outcome equals the oracle's, every conflict replays identically, refusals leave the branch untouched",
           "S4": "100% historical bindings remain pinned (store-level pins and Engine-level Evidence/Verdict bindings; 0 rebinding attempts accepted)",
           "S5": "all target mutations detected (timestamp-dependent projection, missing base-version check, history rebinding), controls clean"}
REJECT = {"R": "Any split-brain, nondeterministic rebuild, silent lost update or history rebinding is observed"}
INCONCLUSIVE = {"I": "Concurrency corpus smaller than the contract minimum, or lacking stale-base / conflicting-change (or any registered) class, or no rebuild/audit/binding population"}
INVALID = {"V1": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
           "V2": "Evidence records disagree on commit / seed / corpus hash, or do not name the current Engine version",
           "V3": f"The Engine or Git store (src/eoo_engine, src/eoo_engine_git) differs from tag {ENGINE_TAG}",
           "V4": "The oracle is not independent of runtime storage (imports / I/O in oracles/h19, or the run did not record an independent oracle)",
           "V5": "Harness files were dirty at run time",
           "V6": "Harness self-check failed (mutation control not clean, harness error rows, summaries disagree with rows, harness files changed since the run)"}


def evaluate(exp_dir, root: Path = ROOT, *, engine_diff=None) -> dict:
    d = Path(exp_dir)
    contract = json.loads((root / "hypotheses/h19/contract.json").read_text())
    th = json.loads((root / "protocol/thresholds.json").read_text())[HID]
    minimum = contract["experiment"]["minimum_runs"]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th, "minimum_unique_scenarios": minimum, "minimum_per_class": MIN_CLASS}
    rb, cs, ca, hb, mu = (pay.get(f) for f in REQUIRED)
    selfcheck = []
    if cs:
        t = storelevel.tally({"scenarios": cs["scenarios"]})
        n.update(store_tally=t, unique_scenarios=len({r["id"] for r in cs["scenarios"]}), class_counts={c: t["classes"].get(c, 0) for c in CLASSES}, oracle_import_audit=cs["oracle"]["import_audit"])
        if t != cs["tally"]:
            problems.append("concurrency-state-machine tally disagrees with its per-write rows")
    if ca:
        s = audit.summarize(ca["cases"])
        n["audit"] = s
        n["direct_write_battery"] = ca["direct_write_battery"]["all_blocked_or_idempotent"]
        if s != ca["summary"]:
            problems.append("canonical-change-audit summary disagrees with its per-step rows")
    if hb and cs and ca:
        n["bindings"] = {"store": {k: hb["store_level"][k] for k in hb["store_level"]}, "engine": hb["engine_level"]}
        if hb["store_level"] != {k: n["store_tally"][k] for k in hb["store_level"]} or hb["engine_level"] != {k: n["audit"][k] for k in hb["engine_level"]}:
            problems.append("historical-binding-results disagree with the rows of the other evidence files")
    if rb:
        n["rebuild"] = {"store": rb["store_histories"], "engine": rb["engine_histories"]}
    if mu:
        by = {m["id"]: m for m in mu["mutants"]}
        n["target_mutants"] = {i: (by[i]["killed"] if i in by and by[i]["target"] else None) for i in TARGETS}
        n["extra_mutants"] = {m["id"]: m["killed"] for m in mu["mutants"] if not m["target"]}
        n["mutant_failing_checks"] = {m["id"]: m["failing_checks"] for m in mu["mutants"]}
        n["mutation_controls_clean"] = [mu["controls"]["clean"], mu["controls"]["clean_after"]]
        n["mutation_exceptions"] = sum(m["exceptions"] for m in mu["mutants"])

    def has(*k):
        return all(x in n for x in k)
    t, a, rbn, bd = n.get("store_tally"), n.get("audit"), n.get("rebuild"), n.get("bindings")
    s1 = (all(p["unequal_commits"] == 0 and p["equal_commits"] == p["unique_commits"] > 0 and p["passes"] >= 2 and p["hash_bijection_violations"] == 0 and p.get("fsck_all_ok", p.get("fsck", True)) is True
              for p in rbn.values()) and t["digest_unstable"] == 0) if rbn and t else None
    s2 = (a["ontology_only_writes"] <= th["max_canonical_ontology_only_writes"] and a["accepted_actions"] > 0 and a["accepted_one_commit"] == a["accepted_traced"] == a["accepted_actions"]
          and a["projection_mismatches"] == 0 and a["refused_moved_branch"] == 0 and a["engine_store_changed"] == 0 and a["non_git_effects"] == 0 and n["direct_write_battery"] is True) if a else None
    s3 = (t["lost_updates"] <= th["max_silent_lost_updates"] and t["silent_wrong_accept"] == 0 and t["writes"] > 0) if t else None
    s3b = (t["outcome_disagreements"] == 0 and t["false_conflicts"] == 0 and t["replays"] == t["replays_equal"] and t["ref_moved_on_refusal"] == 0) if t else None
    s4 = (bd["store"]["binds"] > 0 and bd["store"]["binds_pinned"] == bd["store"]["binds"] and bd["store"]["rebind_accepted"] == 0 and bd["engine"]["bindings"] > 0
          and bd["engine"]["bindings_hash_same"] == bd["engine"]["bindings_entries_same"] == bd["engine"]["bindings"]) if bd else None
    s5 = (all(v is True for v in n["target_mutants"].values()) and all(n["mutation_controls_clean"])) if has("target_mutants") else None
    r = ((rbn["store"]["unequal_commits"] + rbn["engine"]["unequal_commits"] + t["digest_unstable"] > 0) or a["ontology_only_writes"] > 0 or a["projection_mismatches"] > 0
         or t["lost_updates"] > 0 or t["silent_wrong_accept"] > 0 or t["binds"] != t["binds_pinned"] or t["rebind_accepted"] > 0 or bd["engine"]["bindings"] != bd["engine"]["bindings_hash_same"]
         or bd["engine"]["bindings"] != bd["engine"]["bindings_entries_same"]) if (t and a and rbn and bd) else None
    i = (n["unique_scenarios"] < minimum or any(c < MIN_CLASS for c in n["class_counts"].values()) or t["writes"] <= 0 or not rbn or (a is not None and a["accepted_actions"] <= 0)) if t else None
    ed = engine_diff(ENGINE_PATHS) if engine_diff else paths_differing_from_tag(ENGINE_PATHS, ENGINE_TAG)
    oi_now = independence.oracle_imports()
    dirty = {f: dirty_harness_files(rec) for f, rec in recs.items() if dirty_harness_files(rec)}
    stale = [f for f, h in (recs[REQUIRED[0]].get("harness_sha256") or {}).items() if f not in EVALUATOR_FILES and (root / f).exists() and sha_file(root / f) != h] if REQUIRED[0] in recs else []
    if mu is not None and not all(n["mutation_controls_clean"]):
        selfcheck.append("mutation control not clean")
    if t and (t["exceptions"] or (a and a["exceptions"]) or n.get("mutation_exceptions")):
        selfcheck.append(f"harness error rows: store={t['exceptions']} audit={(a or {}).get('exceptions')} mutation={n.get('mutation_exceptions')}")
    if problems and any("disagrees" in p for p in problems):
        selfcheck.append("evidence summaries disagree with their rows")
    if stale:
        selfcheck.append(f"harness files changed since the run: {stale[:5]}")
    oracle_ok = bool(cs) and n["oracle_import_audit"]["independent"] and oi_now["independent"]
    engine_bad = [f for f, rec in recs.items() if rec.get("engine_version") != ENGINE_VERSION]
    n.update(engine_paths_differing_from_tag=ed, oracle_import_audit_now=oi_now, harness_dirty_files_at_run=dirty, harness_self_check=selfcheck)
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S3": s3, "S2": s2, "S3b": s3b, "S4": s4, "S5": s5}), "reject_if": sc.rows(REJECT, {"R": r}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I": i}),
            "invalid_if": sc.rows(INVALID, {"V1": bool(wrong), "V2": len(ident) > 1 or bool(engine_bad), "V3": bool(ed), "V4": bool(cs) and not oracle_ok, "V5": bool(dirty), "V6": bool(selfcheck)})}
    valid = not wrong and len(ident) <= 1 and not engine_bad and not ed and (oracle_ok or not cs) and not dirty and not selfcheck
    return sc.finish(HID, ident[0][3] if ident else None, protocol_valid=valid, complete=not problems, sample_sufficient=(i is False), reject_hit=r is True,
                     support_hit=all(x is True for x in (s1, s2, s3, s3b, s4, s5)), predicates=pred, numbers=n, problems=problems,
                     extra={"engine_version": ENGINE_VERSION, "protocol": {"freeze_sha256": freeze_hash()},
                            "protocol_mismatches": {"records_with_wrong_hashes": wrong, "disagreeing_provenance": len(ident) > 1, "records_not_naming_current_engine_version": engine_bad},
                            "evidence_payload_hashes": {f: x["payload_hash"] for f, x in sorted(recs.items())}, "evaluator_sha256": sha_file(Path(__file__)),
                            "interpretation_notes": ["H19 depends on H18w (author decision 2026-10-05), not on the rejected value claim of H18.",
                                                     "S3b and the lost-update definition (a value the writer set equal to its own base is not a change) are harness definitions, stated in the evidence.",
                                                     "Engine-level histories are checked for rebuild determinism, bijection and projection == Git, not against an oracle DAG prediction (the oracle is domain-blind).",
                                                     "V5 reads the dirty paths recorded in the evidence against the harness files hashed in it (evaluator files excluded)."]})
