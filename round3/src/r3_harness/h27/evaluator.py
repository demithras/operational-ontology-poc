"""H27 contract evaluator (hypotheses/h27/contract.json) with protocol/thresholds.json, per variant.

Everything is recomputed from the raw case records; summaries are only cross-checked. Clauses = ORACLE-AND-HARNESS-G2 B5 +
rulings Q5-Q8: reject on any accepted tamper / rebinding / fallback-to-current / continuation effect / unanchored ack and
(Q8) on any false alarm or binding divergence; INCONCLUSIVE when E1/E2 fail, a tamper class or compound cases are absent,
fewer than 5,000 tampered cases (from >= 300 base histories per domain) or 1,000 clean controls, or anything unsupported;
INVALID when E3/E4/E5 fail, the oracle imports a variant, canonicalization changed, or evidence hashes mismatch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from r3_harness.h23.comparative import security_specific_components, security_specific_loc
from r3_harness.h23.evaluator import oracle_independent
from r3_harness.h24.evaluator import freeze_g2, freeze_g2_mismatches

from .analyze import analyze
from .audit import safe_verify
from .runner import CANON_SHA, FILES, ROUND3

EVAL_FILES = ("evaluator.py", "analyze.py", "corpus.py", "case.py", "tamper.py", "base.py", "layout.py", "mutation.py",
              "audit.py", "stream.py", "gen_history.py")
FROZEN_CANON_SHA = "7e547f31e066255b652214eed88820d69ae84f5807805470d344056f2c0b832b"
MIN_BASES_PER_DOMAIN, MIN_CONTROLS, MIN_COMPOUND_FRACTION = 300, 1000, 0.20  # design numbers (Q7), not thresholds.json


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def _read(p: Path):
    return json.loads(p.read_text())


def minimum_overrides(thresholds: dict, min_tampered, min_bases, min_controls) -> dict:
    frozen = {"min_tampered": thresholds["H27"]["min_provenance_histories"], "min_bases_per_domain": MIN_BASES_PER_DOMAIN,
              "min_controls": MIN_CONTROLS}
    given = {"min_tampered": min_tampered, "min_bases_per_domain": min_bases, "min_controls": min_controls}
    return {k: v for k, v in given.items() if v is not None and v != frozen[k]}


def _evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_tampered=None, min_bases=None, min_controls=None) -> dict:
    t = thresholds["H27"]
    need_t = t["min_provenance_histories"] if min_tampered is None else min_tampered
    need_b = MIN_BASES_PER_DOMAIN if min_bases is None else min_bases
    need_c = MIN_CONTROLS if min_controls is None else min_controls
    reasons: list[str] = []
    valid = True
    ok_ind, bad = oracle_independent()
    if not ok_ind:
        valid, reasons = False, reasons + bad
    drift = freeze_g2_mismatches()
    if drift:
        valid = False
        reasons += ["frozen G2 spec changed: " + d for d in drift]
    missing = [f for f in (*FILES, "envelope.json", "expected-bindings.jsonl") if not (vdir / f).is_file()]
    if missing:
        return _finish(vname, valid, False, False, False, False, reasons + ["required evidence missing: " + ", ".join(missing)], {})
    env = _read(vdir / "envelope.json")
    try:
        evidence.validate_envelope(env)
        ro = env["raw_observations"]
        for f in (*FILES, "expected-bindings.jsonl"):
            if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != ro["evidence_sha256"].get(f):
                valid = False
                reasons.append(f"{f}: sha256 differs from envelope")
        if ro.get("prot_h27_sha256") != freeze_g2()["spec/protections/PROT-H27.md"]:
            valid = False
            reasons.append("PROT-H27.md sha256 in the envelope differs from protocol/FREEZE_G2.json: semantics changed")
        if ro.get("expected_bindings_sha256") != ro["evidence_sha256"].get("expected-bindings.jsonl"):
            valid = False
            reasons.append("expected bindings were not hashed before tampering")
        if ro.get("canonical_bytes_source_sha256") != FROZEN_CANON_SHA or CANON_SHA != FROZEN_CANON_SHA:
            valid = False
            reasons.append("canonicalization changed (canonical_bytes source sha256 != frozen)")
    except Exception as exc:  # noqa: BLE001
        valid = False
        reasons.append(f"envelope invalid: {exc}")
    au = _read(vdir / "anchor-audit.json")
    complete = bool(au.get("finalized"))
    if not complete:
        reasons.append("anchor audit not finalized (E2/E5 missing)")
    anchor_dir = vdir / "anchor"
    e5 = None
    if anchor_dir.is_dir() and au.get("closed_head"):
        e5 = safe_verify(anchor_dir, au["closed_head"])["ok"]
    else:
        complete = False
        reasons.append("anchor directory/closed head missing: E5 cannot be re-verified")
    if au.get("E3_holds") is not True or au.get("E4_all_denied") is not True:
        valid = False
        reasons.append("E3/E4 failed: the anchor directory is writable from the harness process")
    if e5 is False or (au.get("finalized") and au.get("E5_log_integrity") is False):
        valid = False
        reasons.append("E5 failed: anchor log chain/MAC/head verification")
    e12 = au.get("E1_separate_process") is True and au.get("E2_key_only_at_close") is True
    if not e12:
        reasons.append("E1/E2 failed: no independent anchor")
    a = analyze(vdir)
    mut = _read(vdir / "mutation-results.json")
    names = mutants.KNOWN["H27"]
    mut_ok = all(n in mut for n in names)
    killed = sum(1 for n in names if mut.get(n, {}).get("killed") is True)
    kill_rate = killed / len(names) if mut_ok else None
    classes_ok = not a["missing_classes"]
    compound_ok = a["compound_cases"] > 0 and a["compound_cases"] >= MIN_COMPOUND_FRACTION * max(1, a["tampered_cases"])
    dom = a["bases_by_domain"]
    bases_ok = all(dom.get(d, 0) >= need_b for d in ("manufacturing", "project"))
    sample = (e12 and classes_ok and compound_ok and a["tampered_cases"] >= need_t and bases_ok and a["controls"] >= need_c
              and a["unsupported"] == 0 and a["replay_errors"] == 0 and a["deploy_crashes"] == 0)
    for ok, why in ((e12, None), (classes_ok, f"tamper classes absent: {a['missing_classes']}"),
                    (compound_ok, f"compound cases {a['compound_cases']} of {a['tampered_cases']} < {MIN_COMPOUND_FRACTION:.0%}"),
                    (a["tampered_cases"] >= need_t, f"tampered cases {a['tampered_cases']} < {need_t}"),
                    (bases_ok, f"base histories per domain {dom} < {need_b}"),
                    (a["controls"] >= need_c, f"clean controls {a['controls']} < {need_c}"),
                    (a["unsupported"] == 0, f"{a['unsupported']} unsupported results (G2 methods missing)"),
                    (a["replay_errors"] == 0, f"{a['replay_errors']} replay/explain calls raised"),
                    (a["deploy_crashes"] == 0, f"{a['deploy_crashes']} deploy_crash (E-7: deploy raised on history content)")):
        if not ok and why:
            reasons.append(why)
    fb = a["fallback_to_current"]
    false_alarm = a["false_alarms"] + a["binding_divergences"]
    reject = (a["accepted"] > 0 or a["unanchored_ack"] > 0 or fb > t["max_silent_fallback_to_current"]
              or false_alarm > t["max_false_tamper_alarms_on_clean_history"] or a["explain_mismatch"] > 0
              or (a["detection_rate"] is not None and a["detection_rate"] < t["required_tamper_detection_rate"]))
    support = (a["detection_rate"] is not None and a["detection_rate"] >= t["required_tamper_detection_rate"]
               and fb <= t["max_silent_fallback_to_current"] and false_alarm == 0 and a["accepted"] == 0
               and kill_rate is not None and kill_rate >= t["required_mutation_kill_rate"])
    if reject:
        reasons.append(f"accepted={a['accepted']} unanchored_ack={a['unanchored_ack']} fallback={fb} false_alarms+divergences="
                       f"{false_alarm} explain_mismatch={a['explain_mismatch']} detection={a['detection_rate']}")
    if not support and not reject:
        reasons.append(f"support conditions unmet: detection={a['detection_rate']} kill_rate={kill_rate}")
    metrics = {**{k: a[k] for k in ("tampered_cases", "compound_cases", "distinct_bases", "controls", "detection_rate",
                                    "definite_total", "accepted", "fallback_to_current", "false_alarms", "binding_divergences",
                                    "unanchored_ack", "explain_mismatch", "unsupported", "deploy_crashes", "applied_classes", "class_counts")},
               "forbidden_effects": a["accepted"] + a["unanchored_ack"], "safe_progress_ratio": a["clean_verified_ratio"],
               "mutation_kill_rate": kill_rate, "p50_latency_ms": a["latency_ms_per_replay"]["p50"],
               "p95_latency_ms": a["latency_ms_per_replay"]["p95"], "anchor_enforcement": au.get("E3_enforcement"),
               "mutants": {n: mut.get(n, {}).get("killed") for n in names},
               "loc": security_specific_loc(vname), "components": security_specific_components(vname),
               "payload_sha256": env.get("payload_sha256")}
    return _finish(vname, valid, complete and mut_ok, sample, reject, support, reasons, metrics)


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete,
                                         sample_sufficient=sample, reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics}


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_tampered=None, min_bases=None, min_controls=None) -> dict:
    res = _evaluate_variant(vdir, thresholds, vname, min_tampered, min_bases, min_controls)
    ov = minimum_overrides(thresholds, min_tampered, min_bases, min_controls)
    res["minimum_overrides"] = ov
    res["reasons"] = list(res["reasons"]) + [f"DEV ONLY: minimum {k} overridden to {v}" for k, v in ov.items()]
    return res


def evaluate_experiment(exp_dir: Path, thresholds: dict, min_tampered=None, min_bases=None, min_controls=None) -> dict:
    vs = {d.name: evaluate_variant(d, thresholds, d.name, min_tampered, min_bases, min_controls)
          for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    comp = {fld: {n: v["metrics"].get(fld) for n, v in vs.items()}
            for fld in ("forbidden_effects", "safe_progress_ratio", "mutation_kill_rate", "p95_latency_ms")}
    comp["security_specific_loc"] = {n: security_specific_loc(n) for n in vs}
    comp["security_specific_components"] = {n: security_specific_components(n) for n in vs}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H27", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H27"]),
                "minimum_overrides": minimum_overrides(thresholds, min_tampered, min_bases, min_controls), "variants": vs})
    return out
