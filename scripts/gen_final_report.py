#!/usr/bin/env python3
"""experiments/exp-NNN/results/final-report.md — docs/experiment/spec/11
_acceptance_criteria.md "Required final report conclusion" shape
(can_decide_now/can_prove_why_later, ontology_thesis, critical_failures,
tradeoffs). `make report` = this script pointed at the LATEST exp-NNN
directory, re-reading whatever results/*.json already exist WITHOUT
re-running anything (spec 13: "make report regenerates final-report.md
from the results").
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.gen_acceptance_verdict import derive as derive_verdict  # noqa: E402


def _load(results_dir: Path, name: str) -> dict | None:
    p = results_dir / name
    return json.loads(p.read_text()) if p.exists() else None


def _critical_failures(fault_doc, hyps, verdict) -> list[str]:
    out = []
    if fault_doc:
        for m in fault_doc["matrix"]:
            if m["status"] == "FAIL":
                out.append(f"{m['id']} FAIL: {m['description']} — {m.get('note') or ''}".strip())
    for h, rec in (hyps or {}).items():
        if rec.get("status") == "REJECTED":
            out.append(f"{h} REJECTED: {rec.get('notes', '')[:200]}")
    if verdict.get("safety_fail"):
        out.append("Safety zero-tolerance check failed — see acceptance-verdict.json#safety_fail")
    return out


def _tradeoffs(ab, evolution, mutation, hyps) -> dict:
    benefits, costs, unknowns = [], [], []
    h11 = (hyps or {}).get("H11", {})
    if h11.get("status") == "SUPPORTED":
        benefits.append("Declarative structural/state-transition conformance (SHACL) catches a class of "
                         "defect the relational baseline structurally cannot (mutation-results.json "
                         "SHACL_CARDINALITY) — an audit/change-safety benefit, per spec 10's own listed "
                         "'ontology's benefit is audit/governance rather than decision correctness' outcome.")
    if ab:
        w7 = ab.get("W7_generated_incident_corpus", {})
        if w7.get("variants_decision_match_rate") == 1.0:
            costs.append("No correctness advantage measured: both variants reached IDENTICAL governed "
                          "decisions across the full generated incident corpus (W7) — see ab-results.json.")
        ing = ab.get("ingestion_lag_benchmark", {})
        if ing:
            costs.append(f"Ontology ingestion lag measurably higher than the baseline's — see "
                         f"ab-results.json#ingestion_lag_benchmark: {json.dumps(ing)[:300]}")
        costs.append(f"Complexity tax: {json.dumps(ab.get('complexity_tax', {}).get('total_containers_in_stack'))} "
                      f"total containers, {json.dumps(ab.get('complexity_tax', {}).get('ontology_extra_container_count'))} "
                      f"ontology-only extra containers + a second store technology (RDF4J) — see ab-results.json#complexity_tax.")
    if evolution:
        eff = evolution.get("migration_effort", {})
        if not (eff.get("baseline_v1_to_v2_files_touched") or eff.get("baseline_v2_to_v3_files_touched")):
            costs.append("Baseline required ZERO baseline-specific code changes for either contract evolution "
                          "step (shared deployed_version.json); the ontology's own migrations are real, "
                          "measured multi-file diffs — see evolution-comparison.json#migration_effort.")
    unknowns.append("H11's engineering-cost comparison is drawn from ONE clean baseline-build session vs. "
                     "many iterative ontology-build phases — not a time-boxed apples-to-apples methodology "
                     "(disclosed in Phase 8's own notes); treat magnitude, not precision, as the finding.")
    if not benefits:
        unknowns.append("No declared target dimension showed a measurable ontology-specific advantage this "
                         "run — see H11's notes in hypothesis-results.json for the full dimension-by-dimension "
                         "breakdown.")
    return {"benefits": benefits, "costs": costs, "unknowns": unknowns}


def generate(results_dir: Path, exp_version: str) -> str:
    verdict = derive_verdict(results_dir)
    (results_dir / "acceptance-verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")

    hyp_doc = _load(results_dir, "hypothesis-results.json") or {}
    hyps = hyp_doc.get("hypotheses", {})
    fault_doc = _load(results_dir, "fault-results.json")
    ab = _load(results_dir, "ab-results.json")
    evolution = _load(results_dir, "evolution-comparison.json") or _load(REPO_ROOT / "experiments" / "exp-000" / "results", "evolution-comparison.json")
    mutation = _load(results_dir, "mutation-results.json") or _load(REPO_ROOT / "experiments" / "exp-000" / "results", "mutation-results.json")
    test_results = _load(results_dir, "test-results.json")
    env = _load(results_dir, "environment.json") or {}

    critical = _critical_failures(fault_doc, hyps, verdict)
    tradeoffs = _tradeoffs(ab, evolution, mutation, hyps)

    lines: list[str] = []
    lines.append(f"# Final Experiment Report — {exp_version}")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    lines.append(f"Git commit: `{env.get('git_commit', 'unknown')}`")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("```yaml")
    lines.append(f"can_decide_now: {verdict['can_decide_now']}")
    lines.append(f"can_prove_why_later: {verdict['can_prove_why_later']}")
    lines.append("")
    lines.append("ontology_thesis:")
    for h in sorted(hyps, key=lambda k: int(k[1:])):
        lines.append(f"  {h}: {hyps[h]['status']}")
    lines.append("")
    lines.append("critical_failures:")
    if critical:
        for c in critical:
            lines.append(f"  - {json.dumps(c)}")
    else:
        lines.append("  []")
    lines.append("")
    lines.append("tradeoffs:")
    lines.append("  benefits:")
    for b in tradeoffs["benefits"] or ["(none measured this run)"]:
        lines.append(f"    - {json.dumps(b)}")
    lines.append("  costs:")
    for c in tradeoffs["costs"] or ["(none recorded this run)"]:
        lines.append(f"    - {json.dumps(c)}")
    lines.append("  unknowns:")
    for u in tradeoffs["unknowns"]:
        lines.append(f"    - {json.dumps(u)}")
    lines.append("```")
    lines.append("")
    lines.append(f"**Exit code: {verdict['exit_code']}** "
                  f"(0=all mandatory criteria passed, 10=safety, 11=correctness/invariant, 12=replay, "
                  f"13=performance SLO, 14=experiment/baseline invalid, 15=infra/harness failure — "
                  f"experiments/exp-000/manifest.yaml#exit_codes).")
    lines.append("")
    lines.append("## Headline A — can it decide now? Item-by-item")
    lines.append("")
    lines.append("| # | Item | Result |")
    lines.append("|---|---|---|")
    for k, v in verdict["can_decide_now_items"].items():
        lines.append(f"| {k} | | {'PASS' if v is True else ('FAIL' if v is False else 'INCONCLUSIVE (no evidence this run)')} |")
    lines.append("")
    lines.append("## Headline B — can we prove why later? Item-by-item")
    lines.append("")
    lines.append("| # | Item | Result |")
    lines.append("|---|---|---|")
    for k, v in verdict["can_prove_why_later_items"].items():
        lines.append(f"| {k} | | {'PASS' if v is True else ('FAIL' if v is False else 'INCONCLUSIVE (no evidence this run)')} |")
    lines.append("")
    lines.append("## Hypothesis ledger (H1-H14) — full evidence")
    lines.append("")
    for h in sorted(hyps, key=lambda k: int(k[1:])):
        rec = hyps[h]
        lines.append(f"### {h} — {rec['status']}")
        lines.append("")
        lines.append(f"Evidence: {', '.join(rec.get('evidence', []))}")
        lines.append("")
        lines.append(rec.get("notes", ""))
        lines.append("")
    if test_results:
        lines.append("## Test suite summary")
        lines.append("")
        lines.append(f"total={test_results.get('total')}, passed={test_results.get('passed')}, "
                      f"failed={test_results.get('failed')}, errors={test_results.get('errors')}, "
                      f"skipped={test_results.get('skipped')}, elapsed_s={test_results.get('elapsed_s')}")
        lines.append("")
    if fault_doc:
        lines.append("## Fault matrix summary")
        lines.append("")
        lines.append(f"{fault_doc['summary']}")
        lines.append("")

    text = "\n".join(lines) + "\n"
    (results_dir / "final-report.md").write_text(text)
    return text


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    exp_version = sys.argv[2] if len(sys.argv) > 2 else results_dir.parent.name
    generate(results_dir, exp_version)
    print(f"wrote {results_dir / 'final-report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
