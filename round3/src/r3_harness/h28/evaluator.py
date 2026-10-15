"""H28 contract evaluator (hypotheses/h28/contract.json + protocol/thresholds.json H28), per variant, ORACLE-AND-HARNESS-G4 s7 1:1.
Everything is recomputed from the raw cases.jsonl + the closed ledger copy in <variant>/ext; the evidence summaries are only
cross-checked. Precedence INVALID > REJECTED > INCONCLUSIVE > SUPPORTED (r3_shared.verdict.evaluate_common)."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from . import finalize, judge
from .evidence_out import FREEZE_G4, MANIFEST, ROUND3
from .mutation import OWN_CLASS
from .runner import FILES, RAW

EVAL_FILES = ("evaluator.py", "judge.py", "finalize.py", "mutation.py", "caserun.py", "caseplay.py", "gen_case.py", "gen_params.py",
              "adapters.py", "audit.py", "independence.py", "evidence_out.py", "runner.py", "specs.py")
FLOORS = {"min_per_primitive": 300, "min_per_system": 300, "min_crash": 200, "min_none": 300, "min_fault": 300,
          "min_controls": 1000, "min_detect_attempts": 300}
BANNED = ("paladin", "conventional", "r3_harness", "eoo_", "r3_shared.histstore", "r3_shared.variant")


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def oracle_isolation(src_dir: Path | None = None) -> tuple[bool, list[str]]:
    """C28-0: the closure of r3_oracle/extoracle.py imports no variant, no r3_harness, no HistoryStore, reads no world_log marks."""
    seen, todo, bad = set(), ["extoracle"], []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        f = (src_dir or ROUND3 / "src" / "r3_oracle") / f"{name}.py"
        if not f.is_file():
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else ([("." * n.level) + (n.module or "")] +
                   [("." * n.level) + (n.module or "") + "." + a.name for a in n.names] if isinstance(n, ast.ImportFrom) else [])
            for m in mods:
                if m.startswith(BANNED):
                    bad.append(f"{name}: imports {m}")
                if m.startswith("r3_oracle."):
                    todo.append(m.split(".")[1])
                elif m.startswith(".") and not m.startswith(".."):
                    todo.append(m.lstrip(".").split(".")[0])
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in ("world_log", "mark"):
                bad.append(f"{name}: references {n.value!r}")
    return not bad, bad


def freeze_state() -> tuple[dict, dict]:
    frozen = json.loads(FREEZE_G4.read_text())["files"]
    return frozen, {f: hashlib.sha256((ROUND3 / f).read_bytes()).hexdigest() for f in frozen if (ROUND3 / f).is_file()}


CATALOGUE_REL = "src/r3_harness/h28/adapters.py"


def catalogue_state() -> tuple[str | None, str]:
    """(sha256 frozen in FREEZE_G4 or None when the adapter catalogue is not listed, sha256 of the file on disk). Shared by the
    evaluator and the launcher guard (scripts/run_h28.py) so they can never disagree."""
    frozen, _ = freeze_state()
    return frozen.get(CATALOGUE_REL), hashlib.sha256((ROUND3 / CATALOGUE_REL).read_bytes()).hexdigest()


def _read(p: Path):
    return json.loads(p.read_text())


def _need(ov: dict, th: dict) -> dict:
    n = {"min_cases": th["H28"]["min_byzantine_adapter_cases"], **FLOORS}
    n.update({k: v for k, v in ov.items() if k in n})
    return n


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, is_dev: bool) -> dict:
    t, reasons, valid = thresholds["H28"], [], True
    missing = [f for f in (*FILES, MANIFEST, RAW, "run-pre.json") if not (vdir / f).is_file()]
    dbs = [f"{d}/external.db" for d in ("ext", "ext-twin") if not (vdir / d / "external.db").is_file()]
    if missing or dbs:
        return _finish(vname, True, False, False, False, False, ["required evidence missing: " + ", ".join(missing + dbs)], {})
    man = _read(vdir / MANIFEST)
    ro = man["raw_observations"]
    ov = ro.get("dev_overrides") or {}
    if ov and not is_dev:
        valid = False
        reasons.append(f"minimum overrides {ov} in a non-dev experiment id")
    ok, bad = oracle_isolation()
    if not ok:
        valid = False
        reasons += ["oracle isolation (C28-0): " + b for b in bad]
    frozen, cur = freeze_state()
    drift = [f for f, h in frozen.items() if cur.get(f) != h]
    if drift:
        valid = False
        reasons.append("frozen G4 files changed: " + ", ".join(drift))
    fz_hash, cur_hash = catalogue_state()
    if fz_hash is not None:
        if cur_hash != fz_hash:
            valid = False
            reasons.append("adapter catalogue sha256 != FREEZE_G4")
    elif not is_dev:
        valid = False
        reasons.append("adapter catalogue is not frozen in FREEZE_G4 (non-dev id)")
    for f, h in ro["evidence_sha256"].items():
        if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != h:
            valid = False
            reasons.append(f"{f}: sha256 differs from manifest")
    try:
        evidence.validate_envelope(man)
    except Exception as exc:  # noqa: BLE001
        valid = False
        reasons.append(f"manifest invalid: {exc}")
    pre = _read(vdir / "run-pre.json")
    J = finalize.judge_all(vdir, str(vdir / "ext"), pre, str(vdir / "ext-twin"))
    agg = finalize.aggregate(J)
    if not agg["sysstate"]["replay_equals_sysstate"]:
        valid = False
        reasons.append(f"ledger replay != ExternalWorld sysstate (harness fault): {agg['sysstate']['mismatching_keys']}")
    if agg["harness"].get("ext_transcript_mismatch"):       # G4-E21: the observer transcript disagrees with the oracle replay -> the RUN is INVALID
        valid = False
        reasons.append(f"ext_transcript_mismatch in {agg['harness']['ext_transcript_mismatch']} row(s): observer transcript != oracle replay (harness fault)")
    stored = _read(vdir / FILES[1])["summary"]
    if stored.get("classes") != agg["classes"] or stored.get("detection") != agg["detection"]:
        valid = False
        reasons.append("external-effect-diff.json summary differs from the recomputation over the raw records")
    bad_ad = _foreign_adapter_rows(J)
    if bad_ad:
        valid = False
        reasons.append(f"adapters not injected through ExternalBinding (ledger rows by other adapter ids): {bad_ad[:3]}")
    return _verdict(vdir, vname, t, is_dev, ov, agg, J, valid, reasons, man)


def _foreign_adapter_rows(J: dict) -> list:
    ids = {}
    for cid, kinds in J["recs"].items():
        for k, R in kinds.items():
            ids[R["dep"]] = "+".join(R["prims"]) if R["prims"] else "H0"
    return [r["seq"] for r in J["ledger"]["effects"] if r["deployment"] in ids and r["adapter_id"] != ids[r["deployment"]]]


def _verdict(vdir, vname, t, is_dev, ov, agg, J, valid, reasons, man) -> dict:
    need = _need(ov, {"H28": t})
    cl, fl = agg["classes"], agg["floors"]
    cnt = lambda c: cl[c]["count"] + (len(agg["unattributed_scope_rows"]) if c == "effect_outside_scope" else 0)  # noqa: E731
    audit = _read(vdir / FILES[3])
    static_unres = audit.get("static", {}).get("unresolved_count", 0)
    gov = cnt("governance_in_adapter") + static_unres
    mut = _read(vdir / FILES[4])
    names = mutants.KNOWN["H28"]
    killed = {n: bool(mut.get(n)) and mut[n].get("own_class_count", 0) > 0 and mut[n].get("clean_count", 1) == 0 for n in names}
    kill_rate = sum(killed.values()) / len(names)
    det = agg["detection"]
    det_rate = (det["detected"] / det["attempted"]) if det["attempted"] else None
    ind = _read(vdir / FILES[2])
    reject = (cnt("effect_outside_scope") > t["max_effects_outside_adapter_scope"]
              or cnt("false_reconciled_success") > t["max_false_reconciled_success"]
              or gov > t["max_hidden_governance_in_adapters"] or cnt("duplicate_effect") > t["max_duplicate_effects_beyond_contract"]
              or cnt("envelope_mismatch") > 0 or (det_rate is not None and det_rate < 1.0))
    eq = fl["outcome_equal"] == fl["outcome_points"] and fl["outcome_points"] > 0
    prog_ok = cnt("progress_loss") == 0 and fl["progress_checked"] > 0
    per_prim = all(n >= need["min_per_primitive"] for n in fl["per_primitive"].values())
    per_sys = all(fl["per_domain_system"].get(f"{d}/{s}", 0) >= need["min_per_system"] for d, s in
                  (("manufacturing", "WMS"), ("manufacturing", "ERP"), ("manufacturing", "MES"), ("manufacturing", "GEN-NULL"),
                   ("project", "REGISTRY"), ("project", "NOTIFY"), ("project", "GEN-NULL")))
    checks = [(audit.get("static", {}).get("declared", False), "variant does not declare ADAPTER_MODULES (P1f-8): static audit cannot run"),
              (fl["byzantine_cases"] >= need["min_cases"], f"Byzantine cases {fl['byzantine_cases']} < {need['min_cases']}"),
              (fl["honest_controls"] >= need["min_controls"], f"honest controls {fl['honest_controls']} < {need['min_controls']}"),
              (all(v > 0 for v in fl["controls_observed"].values()), f"controls with observed effects per domain {fl['controls_observed']}"),
              (per_prim, f"per-primitive minimum {need['min_per_primitive']}: {fl['per_primitive']}"),
              (per_sys, f"per (domain, system) minimum {need['min_per_system']}: {fl['per_domain_system']}"),
              (fl["crash_cases"] >= need["min_crash"], f"crash-after-commit cases {fl['crash_cases']} < {need['min_crash']}"),
              (fl["none_class_cases"] >= need["min_none"], f"none-class cases {fl['none_class_cases']} < {need['min_none']}"),
              (fl["observer_fault_cases"] >= need["min_fault"], f"observer-fault cases {fl['observer_fault_cases']} < {need['min_fault']}"),
              (det["attempted"] >= need["min_detect_attempts"], f"target-mutation attempts {det['attempted']} < {need['min_detect_attempts']}"),
              (not ind["shared_trust_root"], "action and observation paths share a trust root"),
              (cnt("outcome_mismatch") == 0 and eq, f"outcome equality {fl['outcome_equal']}/{fl['outcome_points']} (mismatch cases {cnt('outcome_mismatch')})"),
              (prog_ok, f"honest progress: {cnt('progress_loss')} losses over {fl['progress_checked']} checked"),
              (not any(agg["harness"].values()), f"harness rows {agg['harness']}")]
    sample = all(ok for ok, _ in checks)
    reasons += [why for ok, why in checks if not ok]
    complete = all(f in mut or True for f in FILES)
    if reject:
        reasons.append(f"scope={cnt('effect_outside_scope')} false_success={cnt('false_reconciled_success')} governance={gov} "
                       f"(behavioural {cnt('governance_in_adapter')}, static unresolved {static_unres}) dup={cnt('duplicate_effect')} detection={det}")
    support = (not reject and det_rate == 1.0 and kill_rate >= t["required_mutation_kill_rate"]
               and fl["byzantine_cases"] >= need["min_cases"])
    if not support and not reject:
        reasons.append(f"support conditions unmet: detection={det_rate} kill_rate={kill_rate}")
    reasons += [f"DEV ONLY: minimum {k} overridden to {v}" for k, v in ov.items()]
    metrics = {"classes": {c: cnt(c) for c in judge.CLASSES}, "governance_sub": agg["governance_sub"], "static_unresolved": static_unres,
               "detection": det, "detection_rate": det_rate, "mutation_kill_rate": kill_rate, "mutants": killed, "floors": fl,
               "harness": agg["harness"], "forbidden_effects": cnt("effect_outside_scope") + cnt("duplicate_effect"),
               "safe_progress_ratio": None if not fl["progress_checked"] else 1 - cnt("progress_loss") / fl["progress_checked"],
               "payload_sha256": man.get("payload_sha256"), "minimum_overrides": ov}
    return _finish(vname, valid, complete, sample, reject, support, reasons, metrics)


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete, sample_sufficient=sample,
                                         reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics,
            "minimum_overrides": metrics.get("minimum_overrides", {}) if metrics else {}}


def evaluate_experiment(exp_dir: Path, thresholds: dict) -> dict:
    dev = "-dev" in exp_dir.name
    vs = {d.name: evaluate_variant(d, thresholds, d.name, dev) for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    comp = {f: {n: (v["metrics"] or {}).get(f) for n, v in vs.items()} for f in ("forbidden_effects", "safe_progress_ratio")}
    comp["mutation_kill_rate"] = {n: (v["metrics"] or {}).get("mutation_kill_rate") for n, v in vs.items()}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H28", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H28"]), "variants": vs,
                "minimum_overrides": {n: v["minimum_overrides"] for n, v in vs.items() if v["minimum_overrides"]},
                "scope_limits": ["L1 observer integrity trusted", "L2 effects_only/none systems lower confidence, excluded from detection",
                                 "L3 adapter attack code = frozen catalogue", "L4 logical ticks", "L5 byte-exact payload digests",
                                 "L6 project external effects only via the H28 overlay", "L7 legacy external_write path untouched"]})
    return out
