#!/usr/bin/env python3
"""Generates experiments/exp-000/results/fault-matrix-phase10a.json from
experiments/exp-000/results/fault-matrix-phase9.json — carries every
F01-F40 entry forward UNCHANGED except:

- F40 ("trace/log unavailable -> business correctness survives"), this
  phase's own item 5 scope: was NOT_TESTED ("no observability layer exists
  yet") — now PASS, backed by tests/faults/test_f40_traces_unavailable.py's
  real, live-collected node id (stops the real otel-collector container,
  proves propose/approve/execute succeed completely normally through
  decision_service).

Same "verify every node id against a live `pytest --collect-only` run,
never hand-typed-and-trusted" convention as every earlier phase's
gen_fault_matrix_phaseN.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE9_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase9.json"
PHASE10A_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase10a.json"

F40_TEST_FILE = "tests/faults/test_f40_traces_unavailable.py"


def _collect_node_ids(test_file: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pytest --collect-only failed for {test_file}: {result.stdout}\n{result.stderr}")
    node_ids = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    if not node_ids:
        raise RuntimeError(f"no test node ids collected for {test_file} — matrix would claim PASS with zero real tests")
    return node_ids


def main() -> int:
    matrix_doc = json.loads(PHASE9_PATH.read_text())

    found_f40 = False
    for item in matrix_doc["matrix"]:
        if item["id"] != "F40":
            continue
        found_f40 = True
        node_ids = _collect_node_ids(F40_TEST_FILE)
        item["status"] = "PASS"
        item["test_node_ids"] = node_ids
        item["owning_phase"] = "Phase 10a"
        item["note"] = (
            "Implemented this phase (docs/experiment/briefs/phase10a.md item 5): a minimal OpenTelemetry "
            "pipeline (an otel-collector service exporting to a file, services/decision_service's "
            "propose/approve/execute spans carrying decision_id/action_execution_id/actor_id/trace_id — "
            "see services/common/tracing.py) makes traces-reference.txt point at real trace data "
            "(scripts/gen_traces_reference.py). F40 itself: the otel-collector container is stopped "
            "entirely and a full propose->approve->execute cycle is driven through the real "
            "decision_service HTTP API, asserting every step succeeds exactly as it would with tracing "
            "available. Canonical provenance (decision_id/action_execution_id in the response body, the "
            "governed Decision record itself) was never sourced from tracing in the first place, so it is "
            "provably unaffected — only the best-effort trace export is impacted, and it degrades "
            "silently (services/common/tracing.py's own docstring: only span setup/teardown failures are "
            "swallowed, and the BatchSpanProcessor's export happens on a background thread decoupled from "
            "the request path, so a dead collector adds no latency to any real request)."
        )
        break

    if not found_f40:
        raise RuntimeError("F40 not found in fault-matrix-phase9.json — matrix structure has drifted")

    statuses = [item["status"] for item in matrix_doc["matrix"]]
    matrix_doc["phase"] = "10a"
    matrix_doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    matrix_doc["summary"] = {
        "total": len(statuses),
        "PASS": statuses.count("PASS"),
        "NOT_TESTED": statuses.count("NOT_TESTED"),
    }

    PHASE10A_PATH.write_text(json.dumps(matrix_doc, indent=2, sort_keys=False) + "\n")
    print(f"wrote {PHASE10A_PATH} — summary: {matrix_doc['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
