"""H29 contract evaluator (hypotheses/h29/contract.json + protocol/thresholds.json H29), per variant, ORACLE-AND-HARNESS-G5 s8 1:1.
Everything is recomputed from the raw cases (cases.jsonl.gz) + the closed service directories (svc/); the evidence files are only
cross-checked. Precedence INVALID > REJECTED > INCONCLUSIVE > SUPPORTED (r3_shared.verdict.evaluate_common).

EVERY branch that differs for dev vs non-dev ids goes through refuse_unless_dev(is_dev, <branch>, ...) so the launcher can mirror each one
as a refusal (G4-E27); DEV_BRANCHES names them and a test enumerates the calls by AST."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from . import aggregate, evalchecks as EC, evidence_out, finalize, judge, reasonmap, specs

DEV_BRANCHES = ("size_overrides", "freeze_manifest", "service_presence", "candidate_tag")
EVAL_FILES = ("evaluator.py", "evalchecks.py", "judge.py", "judge_req.py", "judge_fin.py", "judge_ext.py", "judge_rec.py", "aggregate.py",
              "finalize.py", "evidence_out.py", "runner.py", "driver.py", "rc.py", "inject.py", "collect.py", "gen.py", "gen_eps.py", "gen_emit.py",
              "gen_draw.py", "gen_model.py", "mutation.py", "services.py", "specs.py")
REQUIRED = (*evidence_out.FILES[1:], evidence_out.MANIFEST, "run-pre.json")
NODES_UNRELATED = ("ANCHOR", "OBS", "EXT:WMS", "EXT:ERP", "EXT:MES", "EXT:REGISTRY", "EXT:NOTIFY")   # AUTH: no unrelated op exists (graph)
RATIO = "min_safe_progress_ratio_when_dependencies_available"


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def refuse_unless_dev(is_dev: bool, branch: str, violated: bool, why: str, reasons: list) -> bool:
    """Dev ids may run with the violation (stamped); a non-dev id with it is INVALID. -> True when the run is invalid because of it."""
    assert branch in DEV_BRANCHES, branch
    if violated and not is_dev:
        reasons.append(f"[{branch}] {why}")
        return True
    return False


def _read(p: Path):
    return json.loads(p.read_text())


def _need(ov: dict) -> dict:
    n = dict(EC.FLOORS)
    n.update({k: v for k, v in ov.items() if k in n})
    return n


def _ratio(v):
    return None if not v or not v[0] else v[1] / v[0]


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, is_dev: bool) -> dict:
    t, reasons, valid = thresholds["H29"], [], True
    missing = [f for f in REQUIRED if not (vdir / f).is_file()] + [f for f in ("cases.jsonl.gz",) if not (vdir / f).is_file()]
    if missing or not any((vdir / f).is_file() for f in ("fault-sequences.jsonl", "fault-sequences.jsonl.gz")):
        return _finish(vname, True, False, False, False, False, ["required evidence missing: " + ", ".join(missing)], {})
    man = _read(vdir / evidence_out.MANIFEST)
    ro = man["raw_observations"]
    ov, closes = ro.get("dev_overrides") or {}, ro.get("closes") or {}
    pre = _read(vdir / "run-pre.json")
    W = pre["workers"]
    valid &= not refuse_unless_dev(is_dev, "size_overrides", bool(ov), f"minimum overrides {ov} in a non-dev experiment id", reasons)
    ms = EC.manifest_state()
    bad_m = ms["missing_from_freeze"] + ms["missing_on_disk"]
    valid &= not refuse_unless_dev(is_dev, "freeze_manifest", bool(bad_m), f"{len(bad_m)} freeze-manifest file(s) absent from FREEZE_G5 or from disk: {bad_m[:5]}", reasons)
    have_svc = all(len(closes.get(k) or []) == W and all("error" not in c for c in closes[k]) for k in ("anchor", "ext", "auth"))
    valid &= not refuse_unless_dev(is_dev, "service_presence", not have_svc, "anchor / ExternalWorld / AuthorityService close() outputs missing", reasons)
    valid &= not refuse_unless_dev(is_dev, "candidate_tag", ro.get("candidate", {}).get("head_matches_tag") is not True, "HEAD != candidate tag", reasons)
    ok, bad = EC.oracle_isolation()
    if not ok:
        valid = False
        reasons += ["oracle isolation (C29-0 / invalid_if b): " + b for b in bad]
    frozen, cur = EC.freeze_state()
    drift = [f for f, h in frozen.items() if cur.get(f) != h]
    if drift:
        valid = False
        reasons.append("frozen G5 files changed (invalid_if c/d): " + ", ".join(drift))
    for f in EC.HASH_CLAUSE_C:
        if f in frozen and cur.get(f) != frozen[f]:
            valid = False
            reasons.append(f"invalid_if (c): {f} differs from FREEZE_G5")
    fz, ch = EC.catalogue_state()
    if fz is not None and fz != ch:
        valid = False
        reasons.append("H28 adapter catalogue sha256 != FREEZE_G4 entry")
    for f, h in ro["evidence_sha256"].items():
        if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != h:
            valid = False
            reasons.append(f"{f}: sha256 differs from manifest")
    try:
        evidence.validate_envelope(man)
    except Exception as exc:  # noqa: BLE001
        valid = False
        reasons.append(f"manifest invalid: {exc}")
    (vdir / ".cases.tmp").write_bytes(gzip.open(vdir / "cases.jsonl.gz").read())
    try:
        (vdir / "cases.jsonl").write_bytes((vdir / ".cases.tmp").read_bytes())
        J = finalize.judge_all(vdir, vdir / "svc", W, pre, closes, reasonmap.for_variant(vname))
    finally:
        for f in (".cases.tmp", "cases.jsonl"):
            (vdir / f).unlink(missing_ok=True)
    integ = J["services"]["integrity"]
    for k in ("anchor", "auth"):
        for i, r in enumerate(integ[k]):
            if not r["ok"]:
                valid = False
                reasons.append(f"{k} service {i}: log verification failed (invalid_if d): {r.get('errors') or r}")
    if not J["sysstate"]["replay_equals_sysstate"]:
        valid = False
        reasons.append(f"ledger replay != ExternalWorld sysstate (harness fault): {J['sysstate']['mismatching_keys']}")
    agg = J["agg"]
    stored = _read(vdir / evidence_out.FILES[1])
    if {c: stored["classes"][c]["count"] for c in judge.CLASSES} != {c: agg["classes"][c]["count"] for c in judge.CLASSES}:
        valid = False
        reasons.append("safety-invariants.json differs from the recomputation over the raw records")
    inj = agg["injection"]
    for k, v in sorted(inj.items()):
        if k.startswith("crash:"):
            if v["enforced"] < v["scheduled"]:
                valid = False
                reasons.append(f"invalid_if (a): armed crash point {k} never fired in {v['scheduled'] - v['enforced']} sequence(s)")
        elif v["scheduled"] and v["enforced"] < v["scheduled"]:
            valid = False
            reasons.append(f"invalid_if (a): {k}: server log enforced {v['enforced']}/{v['scheduled']} scheduled windows")
        elif k.split(":")[1] in ("AUTH", "EXT", "ANCHOR") and k.split(":")[0] in ("F2", "F3", "F5") and v["scheduled"] and v["refused_ge1"] / v["scheduled"] < 0.5:
            valid = False
            reasons.append(f"invalid_if (a): {k}: only {v['refused_ge1']}/{v['scheduled']} windows saw a refused call from the deployment")
    return _verdict(vdir, vname, t, is_dev, ov, agg, J, valid, reasons, man)


def _blocked_safe(J: dict) -> dict:
    out = {n: [0, 0] for n in ("AUTH", "ANCHOR")}
    for row in J["rows"]:
        if row["stratum"] != "env":
            continue
        for q in row["req"]:
            for n in out:
                if q.get("cls") == "BLOCKED_BY_DEPENDENCY" and n in (q.get("down") or []):
                    out[n][0] += 1
                elif q.get("cls") == "SAFE_TO_RUN" and n in (q.get("phi") or []):
                    out[n][1] += 1
    return out


def _verdict(vdir, vname, t, is_dev, ov, agg, J, valid, reasons, man) -> dict:
    need = _need(ov)
    cl, pr = agg["classes"], agg["progress"]
    cnt = lambda c: cl[c]["count"]  # noqa: E731
    safety = sum(cnt(c) for c in aggregate.SAFETY)
    rec = agg["recovery"]
    rec_ratio = None if not rec["checks"] else rec["passes"] / rec["checks"]
    ratios = {"overall": _ratio(pr["overall"]), "post_recovery": _ratio(pr["post_recovery"]),
              **{f"class:{c}": _ratio(v) for c, v in pr["per_class"].items()}, **{f"node:{n}": _ratio(v) for n, v in pr["per_node"].items()}}
    low = {k: v for k, v in ratios.items() if v is not None and v < t[RATIO]}
    mis, bnd = cnt("misclassified_dependency_failure"), cnt("boundary_not_explicit")
    reject = (safety > t["max_safety_invariant_violations"] or (rec_ratio is not None and rec_ratio < t["required_recovery_state_equality"])
              or cnt("recovery_nondeterministic") + cnt("recovery_divergence") > 0 or bool(low)
              or mis > t["max_dependency_failure_misclassifications"] or bnd > 0)
    mut = _read(vdir / evidence_out.FILES[5])
    names = mutants.KNOWN["H29"]
    killed = {n: bool(mut.get(n)) and mut[n].get("own_class_count", 0) > 0 and mut[n].get("clean_count", 1) == 0 for n in names}
    kill_rate = sum(killed.values()) / len(names)
    bs = _blocked_safe(J)
    seqc, cps = agg["sequences_with_class"], agg["crash_points"]
    elig_all = pr["overall"][0]
    checks = [(agg["env_sequences"] >= min(t["min_fault_sequences"], need["min_env"]) if not ov else agg["env_sequences"] >= need["min_env"],
               f"S-env sequences {agg['env_sequences']} < {need['min_env'] if ov else t['min_fault_sequences']}"),
              (agg["ctrl_sequences"] >= need["min_ctrl"], f"S-ctrl sequences {agg['ctrl_sequences']} < {need['min_ctrl']}"),
              (all(agg["boundary"].get(b, {}).get("n", 0) >= need["min_bnd_each"] for b in ("B1", "B2", "B3", "B4")), f"boundary probes {agg['boundary']} < {need['min_bnd_each']} each"),
              (all(seqc.get(f"F{k}", 0) >= need["min_class_seqs"] for k in range(1, 9)), f"envelope classes with < {need['min_class_seqs']} sequences: {seqc}"),
              (all(cps.get(cp, 0) >= need["min_cp_seqs"] for cp in J_CPS), f"crash points with < {need['min_cp_seqs']} sequences: {cps}"),
              (all(pr["per_class"][f"F{k}"][0] >= need["min_during_fault"] for k in range(1, 9)),
               f"eligible during-fault requests per class < {need['min_during_fault']}: { {c: v[0] for c, v in pr['per_class'].items()} }"),
              (all(pr["per_node"].get(n, [0, 0])[0] >= need["min_node"] for n in NODES_UNRELATED),
               f"unrelated eligible requests per node < {need['min_node']}: { {n: pr['per_node'].get(n, [0])[0] for n in NODES_UNRELATED} }"),
              (pr["post_recovery"][0] >= need["min_post"], f"post-recovery eligible requests {pr['post_recovery'][0]} < {need['min_post']}"),
              (elig_all > 0 and 100 * pr["during_fault"][0] >= need["min_fault_share_pct"] * elig_all, f"eligible requests sent during an active fault: {pr['during_fault'][0]}/{elig_all} < {need['min_fault_share_pct']}%"),
              (all(bs[n][0] >= need["min_blocked"] and bs[n][1] >= need["min_safe_during"] for n in bs), f"oracle cannot distinguish blocked from healthy per node (BLOCKED, SAFE-during-fault): {bs}"),
              (pr["outcome"][0] > 0 and pr["outcome"][1] == 0, f"outcome_progress_loss {pr['outcome'][1]} over {pr['outcome'][0]} checked intents"),
              (agg["probes"]["in_auth_anchor_window"] >= need["min_probe_window"],
               f"input-invalid probes inside AUTH/ANCHOR fault windows {agg['probes']['in_auth_anchor_window']} < {need['min_probe_window']} (G5-E28)"),
              (rec["checks"] > 0, "no recovery events were judged"),
              (agg["f6_sequences"] > 0 and agg["stale_sensitive_sequences"] == agg["f6_sequences"], f"F6 sequences without a truly stale-sensitive request: {agg['f6_sequences'] - agg['stale_sensitive_sequences']}"),
              (not agg["harness"], f"harness rows {agg['harness']}")]
    sample = all(ok for ok, _ in checks)
    reasons += [why for ok, why in checks if not ok]
    complete = True
    if reject:
        reasons.append(f"safety={safety} {[c for c in aggregate.SAFETY if cnt(c)]} recovery_ratio={rec_ratio} low_ratios={low} misclassified={mis} boundary={bnd}")
    support = (not reject and kill_rate >= t["required_mutation_kill_rate"] and sample)
    if not support and not reject:
        reasons.append(f"support conditions unmet: kill_rate={kill_rate} sample_sufficient={sample}")
    reasons += [f"DEV ONLY: minimum {k} overridden to {v}" for k, v in ov.items()]
    metrics = {"classes": {c: cnt(c) for c in judge.CLASSES}, "ratios": ratios, "recovery_ratio": rec_ratio, "mutants": killed, "mutation_kill_rate": kill_rate,
               "harness": agg["harness"], "forbidden_effects": cnt("forbidden_effect") + cnt("effect_outside_scope") + cnt("duplicate_effect"),
               "safe_progress_ratio": ratios["overall"], "misclassification": agg["misclassification"], "boundary": agg["boundary"],
               "payload_sha256": man.get("payload_sha256"), "minimum_overrides": ov, "blocked_safe": bs, "input_invalid_probes": agg["probes"], "lease_gap": agg["probes"]["lease_gap"], "unrelated_na_by_graph": ["AUTH"]}
    return _finish(vname, valid, complete, sample, reject, support, reasons, metrics)


J_CPS = ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP4_adapter_before_apply", "CP5_adapter_after_apply", "CP6_idle",
         "CP7_reconcile_after_read", "CP8_during_recovery")


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete, sample_sufficient=sample,
                                         reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics, "minimum_overrides": metrics.get("minimum_overrides", {}) if metrics else {}}


def evaluate_experiment(exp_dir: Path, thresholds: dict) -> dict:
    dev = "-dev" in exp_dir.name
    vs = {d.name: evaluate_variant(d, thresholds, d.name, dev) for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    comp = {f: {n: (v["metrics"] or {}).get(f) for n, v in vs.items()} for f in ("forbidden_effects", "safe_progress_ratio", "mutation_kill_rate")}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H29", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H29"]), "variants": vs,
                "minimum_overrides": {n: v["minimum_overrides"] for n, v in vs.items() if v["minimum_overrides"]},
                "scope_limits": ["L1 observer/ExternalWorld/anchor/AuthorityService integrity trusted", "L2 WORLD never faulted (loss = B4)",
                                 "L3 logical ticks", "L4 H25 governance excluded", "L5 Byzantine adapters = frozen H28 catalogue",
                                 "L6 crash = SIGKILL of one host", "L7 legacy cooperative paths untouched"]})
    return out
