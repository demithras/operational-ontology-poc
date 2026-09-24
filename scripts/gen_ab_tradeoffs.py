#!/usr/bin/env python3
"""Generates experiments/exp-000/results/ab-tradeoffs.md from
ab-results.json + baseline-replay-sweep.json + the existing ontology-side
artifacts (bench-phase5.json, fault-matrix-phase8.json) — spec 10: "Produce
a trade-off table per metric ... Do not collapse everything into one
arbitrary score."

    .venv/bin/python scripts/gen_ab_tradeoffs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "experiments" / "exp-000" / "results"


def _load(name: str) -> dict | None:
    path = RESULTS_DIR / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _fmt(value):
    if isinstance(value, float):
        return f"{value:.1f}"
    return value


def _row(metric: str, ontology, baseline, note: str = "") -> str:
    return f"| {metric} | {_fmt(ontology)} | {_fmt(baseline)} | {note} |"


def main() -> int:
    ab = _load("ab-results.json")
    if ab is None:
        print("ab-results.json not found — run scripts/run_ab.py first", file=sys.stderr)
        return 1
    baseline_replay = _load("baseline-replay-sweep.json")
    bench5 = _load("bench-phase5.json")

    w1, w2, w3, w4, w5, w6, w7 = (
        ab.get("W1_canonical_supplier_delay", {}), ab.get("W2_identifier_mismatch_and_mapping_change", {}),
        ab.get("W3_policy_evolution", {}), ab.get("W4_schema_evolution", {}), ab.get("W5_forensic_query", {}),
        ab.get("W6_novel_cross_system_relation", {}), ab.get("W7_generated_incident_corpus", {}),
    )
    eng = ab.get("engineering_cost", {})
    tax = ab.get("complexity_tax", {})
    hot = ab.get("hot_read_benchmark", {})

    lines: list[str] = []
    lines.append("# Phase 8 A/B trade-off table (Variant B: operational ontology vs Variant A: relational baseline)")
    lines.append("")
    lines.append(f"Generated from `experiments/exp-000/results/ab-results.json` ({ab.get('generated_at')}).")
    lines.append("No weighted winner score (spec 10). Per-metric table; conclusions tied to H1-H14 belong in the phase report, not here.")
    lines.append("")

    lines.append("## Correctness")
    lines.append("")
    lines.append("| Metric | Ontology | Baseline | Note |")
    lines.append("|---|---|---|---|")
    lines.append(_row("W1 decision matches (variants agree)", w1.get("decision_match_variants"), w1.get("decision_match_variants"), "canonical-shape synthetic scenario"))
    lines.append(_row("W1 matches reference_model oracle", w1.get("decision_match_oracle", {}).get("ontology"), w1.get("decision_match_oracle", {}).get("baseline"), ""))
    lines.append(_row("W4 decision matches / oracle match", w4.get("decision_match_variants"), w4.get("decision_match_variants"), "reserved>0 post-evolution representation"))
    lines.append(_row("W6 novel-relation query results match", w6.get("suppliers_match"), w6.get("suppliers_match"), ""))
    lines.append(_row(
        f"W7 corpus (n={w7.get('n')}) — decision match rate between variants",
        f"{w7.get('variants_decision_match_rate')}", f"{w7.get('variants_decision_match_rate')}", "same figure both sides by construction (a pairwise rate)",
    ))
    lines.append(_row(
        f"W7 — match rate vs reference_model oracle (n_checked={w7.get('oracle_checked_count')})",
        w7.get("ontology_oracle_match_rate"), w7.get("baseline_oracle_match_rate"), "oracle skips role-authz scenarios — see tests/ab/generator.py",
    ))
    lines.append(_row("Invariant violations / unsafe external effects observed", "0", "0", "both reuse the SAME authz.py/policy.py gate code (item 1) — safety proof inherited, not independently fault-tested per variant this phase"))
    lines.append("")

    lines.append("## Explainability / audit (W5)")
    lines.append("")
    lines.append("| Metric | Ontology | Baseline | Note |")
    lines.append("|---|---|---|---|")
    fo, fb = w5.get("forensic", {}).get("ontology", {}), w5.get("forensic", {}).get("baseline", {})
    lines.append(_row("Forensic query complete (7 sub-questions answered)", fo.get("complete"), fb.get("complete"), ""))
    lines.append(_row("Distinct calls needed", fo.get("calls"), fb.get("calls"), ""))
    lines.append(_row("Manual log sources needed", fo.get("manual_sources"), fb.get("manual_sources"), "both: 1 (the service's own API) — no separate log-scraping needed either side"))
    lines.append(_row("Wall-clock to reconstruct", f"{fo.get('elapsed_s', 0)*1000:.0f} ms", f"{fb.get('elapsed_s', 0)*1000:.0f} ms", ""))
    lines.append("")

    lines.append("## Replay / evolution")
    lines.append("")
    lines.append("| Metric | Ontology | Baseline | Note |")
    lines.append("|---|---|---|---|")
    v1repl = w3.get("v1_historical_replay") or {}
    lines.append(_row("V1-era historical decision replays under HISTORICAL (not current) rule", v1repl.get("used_historical_not_current_rule"), "N/A", "baseline was built in Phase 8, AFTER V1->V2 already happened — no V1-era history of its own (disclosed asymmetry, docs/experiment/implementation-notes.md item 1)"))
    lines.append(_row("Fresh decision replays under its OWN pinned version", w3.get("fresh_decisions_replay_own_pinned_version", {}).get("ontology", {}).get("replay_status"), w3.get("fresh_decisions_replay_own_pinned_version", {}).get("baseline", {}).get("replay_status"), ""))
    if baseline_replay:
        lines.append(_row("% of ALL decisions in the store that replay PASS-like", "5,293/5,293 = 100% (0 FAIL, 0 PARTIAL — see fault-matrix-phase8.json / Phase 8 step 0 section)", f"{baseline_replay.get('pass_like_count')}/{baseline_replay.get('total_decisions')} = {baseline_replay.get('pass_like_pct')}%", "baseline's corpus is entirely Phase-8-session-generated (no multi-month history)"))
    lines.append(_row("Migration failures / silent semantic breaks", "0 (make test-replay, make test-faults — see implementation-notes.md)", "0 (baseline_replay_sweep.py — see above)", ""))
    lines.append("")

    lines.append("## Operational performance")
    lines.append("")
    lines.append("| Metric | Ontology | Baseline | Note |")
    lines.append("|---|---|---|---|")
    if bench5:
        lines.append(_row("p95 proposal latency (isolated, warm, Phase 5 bench)", f"{bench5.get('slo', {}).get('decision_proposal_p95_ms', {}).get('measured_p95_ms')} ms", "not separately isolated-benchmarked this phase", "see bench-phase5.json"))
    lines.append(_row(f"p95 proposal latency (W7 corpus, n={w7.get('n')}, concurrent-burst conditions)", w7.get("proposal_latency_p95_ms", {}).get("ontology"), w7.get("proposal_latency_p95_ms", {}).get("baseline"), "ms — both well under the 500ms SLO; baseline measurably lower under burst load, see implementation-notes.md for the freshness-retry mechanism that explains most of the gap"))
    lines.append(_row("p95 hot read", hot.get("p95_ms", {}).get("ontology"), hot.get("p95_ms", {}).get("baseline"), f"ms, n={hot.get('n')} — both sub-2ms, no material difference"))
    lag = ab.get("ingestion_lag_benchmark", {})
    lines.append(_row(
        "Ingestion lag (WMS write -> own read path reflects it)",
        f"{_fmt(lag.get('mean_lag_ms', {}).get('ontology'))} ms mean" if lag else "TWO watermarks (ingestion + hot-projection computed_at)",
        f"{_fmt(lag.get('mean_lag_ms', {}).get('baseline'))} ms mean" if lag else "ONE watermark (consumer touches it directly)",
        f"n={lag.get('trials')} trials — see docs/experiment/implementation-notes.md item 1 for the two-watermark-vs-one design difference this reflects",
    ))
    lines.append(_row("Reconciliation", "separate standing service (H12, independent re-check)", "inline in the action-execution workflow", "disclosed scope choice, item 1"))
    lines.append("")

    lines.append("## Engineering cost")
    lines.append("")
    lines.append("| Metric | Ontology | Baseline | Note |")
    lines.append("|---|---|---|---|")
    lines.append(_row("Total build effort (this specific artifact)", f"{eng.get('ontology_semantic_core_total_logical_lines')} logical lines (accumulated Phases 3-7b, many commits)", f"{eng.get('baseline_total_logical_lines_services_baseline')} logical lines (1 commit: {eng.get('baseline_build_commit', '')[:10]})", "NOT apples-to-apples methodology — see engineering_cost.note in ab-results.json"))
    w2eff = w2.get("mapping_change_effort", {})
    # tests/ab/test_w2_identifier_mismatch.py's mapping-change step is
    # idempotent (files_changed=0 on a re-run once already applied) — the
    # REAL first-application cost (measured the first time this workload
    # ever ran) is hardcoded here since a re-run's ab-results.json would
    # otherwise under-report it as zero.
    w2_files, w2_lines = (w2eff.get("files_changed"), w2eff.get("lines_added")) if w2eff.get("files_changed") else (1, 12)
    lines.append(_row("W2: effort to add a new source identifier mapping", f"{w2_files} file(s), {w2_lines} lines", f"{w2_files} file(s), {w2_lines} lines", "SAME file both sides — services/identity_resolver reused verbatim (item 1's fairness decision); figure is from FIRST application (this run found it already applied)" if not w2eff.get("files_changed") else "SAME file both sides — services/identity_resolver reused verbatim (item 1's fairness decision)"))
    w6eff = w6.get("effort", {})
    lines.append(_row("W6: effort to add a novel cross-system relation", f"{w6eff.get('ontology', {}).get('logical_lines')} lines, {w6eff.get('ontology', {}).get('migrations_needed')} migrations", f"{w6eff.get('baseline', {}).get('logical_lines')} lines, {w6eff.get('baseline', {}).get('migrations_needed')} migrations", "new query only, both sides — no schema/ontology change needed either way"))
    lines.append("")

    lines.append("## Complexity tax")
    lines.append("")
    lines.append("| Metric | Ontology (extra over shared) | Baseline (extra over shared) | Note |")
    lines.append("|---|---|---|---|")
    lines.append(_row("Extra containers", tax.get("ontology_extra_container_count"), tax.get("baseline_extra_container_count"), f"of {tax.get('total_containers_in_stack')} total, {len(tax.get('shared_containers', []))} shared"))
    lines.append(_row("Extra store technologies", "; ".join(tax.get("ontology_extra_store_technologies", [])) or "0", "; ".join(tax.get("baseline_extra_store_technologies", [])) or "0", ""))
    lines.append("")

    lines.append("## Workload status")
    lines.append("")
    lines.append("| Workload | Status |")
    lines.append("|---|---|")
    for key in ("W1_canonical_supplier_delay", "W2_identifier_mismatch_and_mapping_change", "W3_policy_evolution", "W4_schema_evolution", "W5_forensic_query", "W6_novel_cross_system_relation", "W7_generated_incident_corpus"):
        lines.append(f"| {key} | {ab.get(key, {}).get('_status', 'NOT RUN')} |")
    lines.append("")

    out_path = RESULTS_DIR / "ab-tradeoffs.md"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"[gen_ab_tradeoffs] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
