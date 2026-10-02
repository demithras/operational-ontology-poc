"""Frozen H22 evaluator: evidence directory -> verdict.json. The domain gate (h22_gate) decides BEFORE any trend is read.

One named predicate per contract clause, each with its numbers. No SUPPORTED/REJECTED trend verdict is possible with fewer than
three real domains or fewer than 30 completed blind tasks (contract stop condition). Missing evidence never supports.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, sha_file
from hdd.verdict import h22_gate

from . import fairness
from .run import HID, JSON_REQUIRED

SUPPORT = {
    "S1": "At least 3 independently useful real domains are included",
    "S2": "For >= 2 independent preregistered task classes, median normalized adaptation effort <= 0.75 of baseline with correctness/security non-inferior",
    "S3": "Overall marginal adaptation-cost slope across real domains <= 0.75 of baseline slope, with uncertainty reported",
    "S4": "A realistic workload tier exists where measured gains are not dominated by recurring ontology tax",
}
REJECT = {
    "R1": "With >= 3 real domains and >= 30 tasks: all preregistered task classes have ratio >= 0.90, or the baseline has equal/lower marginal slope (ratio >= 1.0)",
    "R2": "With the gate open: apparent savings disappear under fair baseline tooling or require a correctness/security regression",
}
INCONCLUSIVE = {"I1": "Fewer than 3 real domains, fewer than 30 completed blind tasks, or the slope uncertainty spans both the support (<= 0.75) and reject (>= 0.90) regions"}
INVALID = {
    "V1": "Task corpus, cost metric or baseline capability changed after reveal",
    "V2": "Cost accounting is asymmetric: one variant's equivalent glue / recurring tax is not counted (per-task components or the H18 context snapshot)",
    "V3": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
    "V4": "Evidence records disagree on commit / seed / corpus hash",
}
REVEAL_KEYS = ("corpus_sha256", "cost_metric_sha256", "baseline_sha256")


def _domains(mf) -> list[str]:
    return sorted({d["id"] for d in (sc.g(mf, "real_domains", default=[]) or []) if d.get("real") is True and d.get("evidence_it_is_real") and not d.get("synthetic")})


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H22"]
    recs, pay, problems = sc.load_evidence(d, HID, JSON_REQUIRED, root)
    md = d / "tradeoff-frontier.md"
    if not md.is_file() or not md.read_text().strip():
        problems.append("tradeoff-frontier.md: missing or empty")
    wrong, ident = sc.protocol_state(recs, root)
    mf, bt, ac, cs, rt, tr = (pay.get(f) for f in JSON_REQUIRED)
    real = _domains(mf) if mf else []
    done = {}
    for t in (sc.g(bt, "tasks", default=[]) or []):
        if t.get("status") == "complete" and t.get("domain") in real and t.get("task_id"):
            done[t["task_id"]] = t
    rows = {t["task_id"]: t for t in (sc.g(ac, "per_task", default=[]) or []) if t.get("task_id") in done}
    completed = len(rows)
    by_class: dict[str, list[float]] = {}
    for tid, t in rows.items():
        if (t.get("baseline_cost") or 0) > 0 and t.get("eoo_cost") is not None:
            by_class.setdefault(done[tid]["task_class"], []).append(t["eoo_cost"] / t["baseline_cost"])
    median = {c: statistics.median(v) for c, v in sorted(by_class.items())}
    noninf = {c: sc.g(cs, "per_class", c, "non_inferior") is True for c in median}
    slope, lo, hi = (sc.g(tr, k) for k in ("slope_ratio", "ci_low", "ci_high"))
    regress = sc.g(cs, "regressions", default=None)
    gate = h22_gate(len(real), completed, min_domains=th["min_real_domains_for_verdict"], min_tasks=th["min_blind_tasks"])
    sup_cls = [c for c, m in median.items() if m <= th["support_max_median_adaptation_ratio"]]
    sup_ok = [c for c in sup_cls if noninf[c]]
    unc_known = isinstance(slope, (int, float)) and isinstance(lo, (int, float)) and isinstance(hi, (int, float))
    spans = unc_known and lo <= th["support_max_slope_ratio"] and hi >= th["reject_min_adaptation_ratio_all_classes"]
    apparent = len(sup_cls) >= th["min_independent_task_classes_with_support_gain"] and unc_known and slope <= th["support_max_slope_ratio"]
    fair_persist = sc.g(rt, "fair_baseline_savings_persist")
    asym = fairness.task_asymmetries(list(rows.values())) + (fairness.asymmetries(sc.g(rt, "fairness_context", "h18_snapshot")) if sc.g(rt, "fairness_context", "h18_snapshot") else [])
    reveal, cur = sc.g(bt, "reveal"), sc.g(bt, "current_hashes")
    n = {"thresholds": th, "real_domains": real, "real_domain_count": len(real), "stated_real_domain_count": sc.g(mf, "real_domain_count"),
         "candidate_d3_sources": sc.g(mf, "candidate_d3_sources"), "completed_blind_tasks": completed, "gate_open": gate,
         "median_ratio_by_class": median, "classes_with_support_gain": sup_cls, "classes_supported_noninferior": sup_ok, "slope_ratio": slope,
         "slope_ci": [lo, hi], "uncertainty_spans_support_and_reject": bool(spans), "regressions": regress, "fair_baseline_savings_persist": fair_persist,
         "accounting_asymmetries": asym, "wrong_provenance_files": wrong}
    s1 = len(real) >= th["min_real_domains_for_verdict"] if mf else None
    s2 = len(sup_ok) >= th["min_independent_task_classes_with_support_gain"] if (ac and cs) else None
    s3 = (unc_known and slope <= th["support_max_slope_ratio"]) if tr else None
    s4 = (sc.g(rt, "realistic_tier_gain_not_dominated_by_tax") is True) if rt else None
    r1 = (gate and bool(median) and (all(m >= th["reject_min_adaptation_ratio_all_classes"] for m in median.values()) or (isinstance(slope, (int, float)) and slope >= 1.0))) if (mf and ac) else None
    r2 = (gate and apparent and (fair_persist is False or bool(regress) or any(not noninf[c] for c in sup_cls))) if (mf and ac) else None
    i1 = (len(real) < th["min_real_domains_for_verdict"] or completed < th["min_blind_tasks"] or bool(spans)) if mf else None
    v1 = bool(reveal) and any((cur or {}).get(k) != reveal.get(k) for k in REVEAL_KEYS) if bt else None
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4}), "reject_if": sc.rows(REJECT, {"R1": r1, "R2": r2}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1}),
            "invalid_if": sc.rows(INVALID, {"V1": v1, "V2": bool(asym), "V3": bool(wrong), "V4": len(ident) > 1})}
    return sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not (v1 or asym or wrong or len(ident) > 1), complete=not problems,
                     sample_sufficient=bool(gate) and not spans, reject_hit=bool(r1 or r2), support_hit=all(x is True for x in (s1, s2, s3, s4)),
                     predicates=pred, numbers=n, problems=problems,
                     extra={"protocol": {"freeze_sha256": freeze_hash()}, "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
                            "evaluator_sha256": sha_file(Path(__file__)), "gate": {"real_domains": len(real), "completed_blind_tasks": completed, "open": bool(gate)},
                            "interpretation_notes": [
                                "DEVELOPMENT RUN unless the experiment id is exp-h22-001 produced by the orchestrator in an isolated worktree.",
                                "Gate-closed state: the verdict is INCONCLUSIVE by the preregistered domain gate; context numbers are not a trend and feed no support/reject clause.",
                                "Slope-uncertainty rule (this evaluator's reading of 'spans both regions'): CI lower bound <= 0.75 and upper bound >= 0.90.",
                                "R1 'baseline has equal/lower marginal slope' is read as slope ratio >= 1.0."]})
