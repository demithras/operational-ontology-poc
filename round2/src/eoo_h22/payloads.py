"""The seven H22 evidence payloads for the gate-closed state (2 real domains, 0 blind tasks, no D3 source registered). Honest not-run."""
from __future__ import annotations

from . import facts, fairness

CLASSES = ["source_churn", "new_relation_query", "policy_composition", "action_addition", "interface_reuse"]
GATE_REASON = "gate closed: 2 real domains < 3 (protocol/thresholds.json H22.min_real_domains_for_verdict) and 0 blind tasks < 30; no D3+ source is registered"
NOT_RUN = {"status": "not-run", "reason": GATE_REASON}


def domain_manifest() -> dict:
    return {
        "min_real_domains_for_verdict": 3,
        "real_domains": [
            {"id": "D1", "name": "manufacturing", "real": True, "independently_useful": True,
             "evidence_it_is_real": ["this repository's v1 POC contracts (repo-root contracts/, services/, seed/, migrations/, tests/: a running manufacturing/WMS stack)",
                                     "round2/domains/manufacturing/ir.json (Gate-0 IR authored from those contracts, unchanged)"]},
            {"id": "D2", "name": "project", "real": True, "independently_useful": True,
             "evidence_it_is_real": ["this repository's own research lifecycle (hypotheses, experiments, evidence, verdicts, decisions, replications)",
                                     "round2/domains/project/ir.json and ir.v2.json (authored after the freeze, executed by the Engine)"]}],
        "real_domain_count": 2,
        "candidate_d3_sources": [],
        "candidate_d3_note": "NONE registered. No synthetic domain may be counted as real (ENGINE_PREREG H22).",
        "synthetic_domains_counted_as_real": 0,
    }


def blind_task_results() -> dict:
    return {**NOT_RUN, "preregistered_task_classes": CLASSES, "tasks_completed": 0, "tasks": [],
            "minimum_blind_tasks": 30, "reveal": None, "note": "no blind task corpus was frozen, revealed or run"}


def adaptation_costs() -> dict:
    return {**NOT_RUN, "per_task": [], "cost_metric": "files/LOC/components/migrations/bespoke tools/time-to-green/regressions (not applied: no tasks)",
            "accounting": {"eoo_counted": [], "baseline_counted": []}, "reveal": None}


def correctness_security() -> dict:
    return {**NOT_RUN, "per_class": {}, "regressions": 0, "note": "no per-task oracle was run; absence of regressions is NOT claimed"}


def runtime_tax(ctx: dict, snap: dict) -> dict:
    return {**NOT_RUN, "realistic_tier": None, "realistic_tier_gain_not_dominated_by_tax": None, "context": ctx,
            "fairness_context": {"h18_snapshot": snap, "asymmetries": fairness.asymmetries(snap)}}


def trend_analysis() -> dict:
    return {**NOT_RUN, "slope_ratio": None, "ci_low": None, "ci_high": None, "domains_in_fit": 0,
            "note": "a marginal slope needs >= 3 real domains; with 2 points no confidence interval exists"}


def frontier_md(ctx: dict, vd: str = "INCONCLUSIVE (domain gate)") -> str:
    r = ctx["h18_ratio_eoo_over_baseline_by_class"]
    return f"""# H22 trade-off frontier (development run)

STATUS: not-run. {GATE_REASON}.

No trade-off frontier can be drawn: it needs at least three real domains and 30 completed blind tasks.
This file reports no weighted winner score and no trend. Expected verdict from the preregistered domain gate: {vd}.

## Context, not trend (committed single-domain facts, read from evidence)

- H15 (OpenPona vs the direct DSL, text size ratio): manufacturing lines {ctx['h15_openpona_over_dsl_ratios']['manufacturing']['lines']:.2f}x, project lines {ctx['h15_openpona_over_dsl_ratios']['project']['lines']:.2f}x; compiler LOC {ctx['h15_compiler_loc']['openpona']} vs {ctx['h15_compiler_loc']['dsl']}.
- H18 (project domain, EOO vs file-only baseline, total changed LOC ratio): TC1 {r['TC1']}, TC2 {r['TC2']}, TC3 {r['TC3']} (above 1 = EOO larger); H18 verdict {ctx['committed_verdicts']['H18']}.
- Recurring complexity LOC: EOO {ctx['h18_recurring_complexity_loc']['eoo']} vs baseline {ctx['h18_recurring_complexity_loc']['baseline']}.
- Engine/toolchain LOC: """ + ", ".join(f"{k.split('/')[-1]} {v['lines']}" for k, v in ctx["engine_toolchain_loc"].items()) + """.

These are one domain / one task set each. They say nothing about how marginal cost changes with the number of domains.
"""
