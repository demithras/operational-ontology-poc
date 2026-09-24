#!/usr/bin/env python3
"""Derives experiments/exp-NNN/results/fault-results.json (spec 13/11
shape: F01-F40, each PASS/FAIL/NOT_TESTED with a test-id pointer) from
THIS RUN's own test-results.json (scripts/run_full_test_suite.py's junit-
derived per-test outcomes) — never carried forward/hand-typed. The curated
F-id -> description/test_node_ids/owning_phase mapping (built up
incrementally since Phase 6b) is read from
experiments/exp-000/results/fault-matrix-phase10a.json as the catalog of
WHAT each fault id means and WHICH tests exercise it; only the per-id
STATUS is re-derived from this run's live outcomes.

Any F-id whose mapped test node ids are absent from this run's test-results
(e.g. a file renamed, or the suite scoped narrower than the catalog
expects) is honestly reported NOT_TESTED with a reason — never silently
dropped or carried forward as a stale PASS (common.md honesty rule).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase10a.json"


def _status_for(test_node_ids: list[str], test_outcomes: dict[str, dict]) -> tuple[str, str | None]:
    if not test_node_ids:
        return "NOT_TESTED", "no test node ids mapped for this fault id"
    found = {t: test_outcomes.get(t) for t in test_node_ids}
    missing = [t for t, v in found.items() if v is None]
    if len(missing) == len(test_node_ids):
        return "NOT_TESTED", f"none of the mapped test node ids were collected/run this session: {test_node_ids}"
    ran = {t: v for t, v in found.items() if v is not None}
    bad = {t: v for t, v in ran.items() if v["outcome"] in ("failed", "error")}
    if bad:
        reason = "; ".join(f"{t}: {v['outcome']}" for t, v in bad.items())
        return "FAIL", reason
    skipped_only = all(v["outcome"] == "skipped" for v in ran.values())
    if skipped_only:
        return "NOT_TESTED", f"all mapped tests were SKIPPED this run: {list(ran.keys())}"
    note = None
    if missing:
        note = f"partial coverage this run — not collected: {missing}"
    return "PASS", note


def generate(results_dir: Path) -> dict:
    test_results_path = results_dir / "test-results.json"
    if not test_results_path.exists():
        raise RuntimeError(f"{test_results_path} does not exist — run scripts/run_full_test_suite.py first")
    test_results = json.loads(test_results_path.read_text())
    test_outcomes = test_results.get("tests", {})
    catalog = json.loads(CATALOG_PATH.read_text())

    matrix = []
    for item in catalog["matrix"]:
        status, note = _status_for(item.get("test_node_ids") or [], test_outcomes)
        matrix.append({
            "id": item["id"],
            "description": item["description"],
            "status": status,
            "test_ids": item.get("test_node_ids") or [],
            "owning_phase": item.get("owning_phase"),
            "note": note or item.get("note"),
        })

    def aux(key: str) -> dict:
        block = catalog[key]
        status, note = _status_for(block.get("test_node_ids") or [], test_outcomes)
        return {"description": block["description"], "status": status, "test_ids": block.get("test_node_ids") or [], "note": note}

    counts = {"PASS": 0, "FAIL": 0, "NOT_TESTED": 0}
    for item in matrix:
        counts[item["status"]] += 1

    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "derived_from": str(test_results_path.relative_to(REPO_ROOT)),
        "summary": {"total": len(matrix), **counts},
        "matrix": matrix,
        "kill_tests": aux("kill_tests"),
        "network_tests": aux("network_tests"),
        "concurrency_test": aux("concurrency_test"),
    }
    out_path = results_dir / "fault-results.json"
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps(doc["summary"], indent=2))
    return doc


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    doc = generate(results_dir)
    return 0 if doc["summary"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
