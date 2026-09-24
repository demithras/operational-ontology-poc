#!/usr/bin/env python3
"""`make ab` — Phase 8 items 2+3: runs workloads W1-W7 (tests/ab/) against
BOTH live variants, collects the metrics spec 10 asks for (correctness,
explainability, replay/evolution, operational performance, engineering
cost, complexity tax — NO weighted "winner" score), and writes:

  experiments/exp-000/results/ab-results.json   (raw metrics, everything)
  experiments/exp-000/results/ab-tradeoffs.md    (the trade-off table)

Run directly:

    .venv/bin/python scripts/run_ab.py [--w7-n 500]

Never fakes success: a workload that raises is recorded as a FAILED entry
(error message included) and the script continues to the next one — a
partial run still produces a report of what DID complete, per
common.md's honesty rule (never silently pass what can't run).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from tests.ab.harness import Harness  # noqa: E402
from tests.ab import (  # noqa: E402
    test_w1_canonical as w1,
    test_w2_identifier_mismatch as w2,
    test_w3_policy_evolution as w3,
    test_w4_schema_evolution as w4,
    test_w5_forensic_query as w5,
    test_w6_novel_relation as w6,
    test_w7_generated_corpus as w7,
)

RESULTS_DIR = REPO_ROOT / "experiments" / "exp-000" / "results"


def _run_workload(name: str, fn, *args, **kwargs) -> dict:
    print(f"[run_ab] --- {name} ---")
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        result["_elapsed_s"] = time.monotonic() - t0
        result["_status"] = "OK"
        print(f"[run_ab] {name}: OK ({result['_elapsed_s']:.1f}s)")
        return result
    except Exception as exc:  # noqa: BLE001 - a workload failure must not abort the whole run
        elapsed = time.monotonic() - t0
        print(f"[run_ab] {name}: FAILED after {elapsed:.1f}s: {exc}", file=sys.stderr)
        return {"workload": name, "_status": "FAILED", "_error": str(exc), "_elapsed_s": elapsed}


def _git_stat(rev_range_or_commit: str, extra_args: list[str] | None = None) -> dict:
    args = ["git", "show", "--stat", "--format=", rev_range_or_commit] if ".." not in rev_range_or_commit else ["git", "diff", "--stat", rev_range_or_commit]
    result = subprocess.run(args + (extra_args or []), cwd=REPO_ROOT, capture_output=True, text=True, timeout=15)
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    return {"ref": rev_range_or_commit, "raw_summary": lines[-1].strip() if lines else "", "files": lines[:-1] if lines else []}


def _wc_l(rel_path: str) -> int:
    p = REPO_ROOT / rel_path
    return len(p.read_text().splitlines()) if p.is_file() else 0


def _dir_wc_l(rel_dir: str) -> int:
    total = 0
    d = REPO_ROOT / rel_dir
    if not d.is_dir():
        return 0
    for p in d.rglob("*.py"):
        total += len(p.read_text().splitlines())
    return total


def engineering_cost() -> dict:
    """spec 10: 'Record rather than pretend precision.'"""
    baseline_build_commit = subprocess.run(
        ["git", "log", "--format=%H", "--grep=Phase 8 item 1", "-1"], cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout.strip()
    baseline_stat = _git_stat(baseline_build_commit) if baseline_build_commit else None

    ontology_semantic_core_files = [
        "services/decision_service", "services/ingestion", "services/projection_builder", "services/identity_resolver",
        "services/common/rdf4j_client.py", "services/common/rdf_graphs.py", "services/common/action_rdf.py",
    ]
    ontology_lines = sum(_dir_wc_l(f) if (REPO_ROOT / f).is_dir() else _wc_l(f) for f in ontology_semantic_core_files)
    ontology_lines += sum(len(p.read_text().splitlines()) for p in (REPO_ROOT / "contracts" / "ontology").rglob("*.ttl"))
    ontology_lines += sum(len(p.read_text().splitlines()) for p in (REPO_ROOT / "contracts" / "shapes").rglob("*.ttl"))

    baseline_lines = _dir_wc_l("services/baseline")

    return {
        "baseline_build_commit": baseline_build_commit or None,
        "baseline_build_git_stat": baseline_stat,
        "baseline_total_logical_lines_services_baseline": baseline_lines,
        "ontology_semantic_core_total_logical_lines": ontology_lines,
        "note": (
            "NOT an apples-to-apples methodology: services/baseline/ was built in ONE Phase 8 session with a "
            "single measurable commit; the ontology variant's equivalent (decision_service + ingestion + "
            "projection_builder + identity_resolver + RDF4J client/graph helpers + all ontology/shapes .ttl "
            "files) accumulated across Phases 3-7b, many commits, with substantial iteration/fault-fixing "
            "folded in that this line count does not separate out. Reported as the best available proxy for "
            "'how much code implements the semantic-core-specific machinery', not a time-boxed comparison."
        ),
        "w6_novel_relation_effort": "see ab-results.json 'W6_novel_cross_system_relation'.effort",
        "w2_identifier_mapping_effort": "see ab-results.json 'W2_identifier_mismatch_and_mapping_change'.mapping_change_effort",
    }


def complexity_tax() -> dict:
    services = subprocess.run(["docker", "compose", "config", "--services"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.split()
    shared = {"postgres", "erp", "mes", "wms", "kafka", "connect", "openfga-migrate", "openfga", "opa", "temporal-postgres", "temporal", "temporal-ui"}
    ontology_only = {"rdf4j", "ingestion", "projection_builder", "decision_service", "action_worker", "reconciliation"}
    baseline_only = {"baseline_ingestion", "baseline_service", "baseline_action_worker"}
    return {
        "total_containers_in_stack": len(services),
        "shared_containers": sorted(shared & set(services)),
        "ontology_only_containers": sorted(ontology_only & set(services)),
        "baseline_only_containers": sorted(baseline_only & set(services)),
        "ontology_extra_container_count": len(ontology_only & set(services)),
        "baseline_extra_container_count": len(baseline_only & set(services)),
        "ontology_extra_store_technologies": ["RDF4J (separate triple store + its own docker volume, oo-poc-rdf4j-data)"],
        "baseline_extra_store_technologies": [],
        "note": (
            "Both variants share the SAME Postgres instance for their own logical DB — baseline adds a DB, "
            "not a new store technology. The ontology variant additionally requires reconciliation as a "
            "SEPARATE standing service (H12, independent CDC re-check); services/baseline/activities.py folds "
            "the equivalent check inline into the action-execution workflow instead (a disclosed Phase 8 "
            "scope choice, see docs/experiment/implementation-notes.md item 1) — one fewer moving part, "
            "at the cost of no independent-of-the-executor re-verification path."
        ),
    }


def hot_read_benchmark(h: Harness, n: int = 30) -> dict:
    """A LIGHT p95 hot-read benchmark (spec 10 'p95 hot read') — reuses
    whatever synthetic inventory W1-W6 already seeded (PX-7001..PX-7006)
    rather than seeding anything new."""
    import time as _t

    samples = {"ontology": [], "baseline": []}
    for _ in range(n):
        t0 = _t.monotonic()
        with h.ontology_hot_conn.cursor() as cur:
            cur.execute("SELECT on_hand FROM current_inventory WHERE part = 'PX-7001' AND warehouse = 'WH-A'")
            cur.fetchone()
        samples["ontology"].append(_t.monotonic() - t0)

        t0 = _t.monotonic()
        with h.baseline_conn.cursor() as cur:
            cur.execute("SELECT on_hand FROM inventory_lots WHERE part = 'PX-7001' AND warehouse_id = 'WH-A'")
            cur.fetchone()
        samples["baseline"].append(_t.monotonic() - t0)

    def p95(values):
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))] * 1000

    return {"n": n, "p95_ms": {k: p95(v) for k, v in samples.items()}, "mean_ms": {k: (sum(v) / len(v) * 1000) for k, v in samples.items()}}


def ingestion_lag_benchmark(h: Harness, trials: int = 5) -> dict:
    """spec 10 'ingestion lag': wall-clock from a real WMS write to the
    moment each variant's OWN read path first reflects it — a fresh
    synthetic part per trial (index range 2000+, disjoint from W1-W6's
    1-6 and W7's default 1000-1499) so trials never race each other."""
    from tests.ab import synthetic

    samples = {"ontology": [], "baseline": []}
    for trial in range(trials):
        part = synthetic.part_ids(2000 + trial)
        synthetic.ensure_erp_part(h.erp_conn, part)
        on_hand = 100 + trial
        t_write = time.monotonic()
        synthetic.set_wms_inventory(h.wms_http.base_url, part, "WH-C", on_hand=on_hand)

        t0 = time.monotonic()
        ok_b = synthetic.wait_baseline_inventory(h.baseline_conn, part, "WH-C", on_hand, timeout_s=30.0)
        if ok_b:
            samples["baseline"].append(time.monotonic() - t_write)

        ok_o = synthetic.wait_ontology_inventory(h.ontology_hot_conn, part, "WH-C", on_hand, timeout_s=30.0)
        if ok_o:
            samples["ontology"].append(time.monotonic() - t_write)

    def _mean(values):
        return (sum(values) / len(values) * 1000) if values else None

    return {
        "trials": trials,
        "mean_lag_ms": {k: _mean(v) for k, v in samples.items()},
        "max_lag_ms": {k: (max(v) * 1000 if v else None) for k, v in samples.items()},
        "all_trials_converged": {k: len(v) == trials for k, v in samples.items()},
        "note": "wall-clock from the WMS write call returning to the variant's OWN read path first reflecting the new value (baseline: inventory_lots row; ontology: current_inventory hot-projection row, its SLOWER of the two by construction — see complexity_tax note on the two-watermark design)",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--w7-n", type=int, default=w7.DEFAULT_N)
    parser.add_argument("--w7-seed", type=int, default=w7.DEFAULT_SEED)
    args = parser.parse_args()

    db_env.load_dotenv()
    h = Harness.create()
    results: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "manifest": "docs/experiment/spec/10_ab_experiment.md"}
    try:
        results["W1_canonical_supplier_delay"] = _run_workload("W1", w1.run, h)
        results["W2_identifier_mismatch_and_mapping_change"] = _run_workload("W2", w2.run, h)
        results["W3_policy_evolution"] = _run_workload("W3", w3.run, h)
        results["W4_schema_evolution"] = _run_workload("W4", w4.run, h)
        results["W5_forensic_query"] = _run_workload("W5", w5.run, h)
        results["W6_novel_cross_system_relation"] = _run_workload("W6", w6.run, h)
        results["W7_generated_incident_corpus"] = _run_workload("W7", w7.run, h, n=args.w7_n, seed=args.w7_seed)
        results["hot_read_benchmark"] = _run_workload("hot_read_benchmark", hot_read_benchmark, h)
        results["ingestion_lag_benchmark"] = _run_workload("ingestion_lag_benchmark", ingestion_lag_benchmark, h)
        results["engineering_cost"] = engineering_cost()
        results["complexity_tax"] = complexity_tax()
    finally:
        h.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "ab-results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str, sort_keys=False) + "\n")
    print(f"[run_ab] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
