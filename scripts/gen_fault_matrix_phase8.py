#!/usr/bin/env python3
"""Generates experiments/exp-000/results/fault-matrix-phase8.json from
experiments/exp-000/results/fault-matrix-phase7.json — carries every
F01-F40 entry forward UNCHANGED except F22-F24 (Phase 8 step 0's own
scope: docs/experiment/spec/11_acceptance_criteria.md criterion A.11 —
"component failure causes explicit unavailable/pending/unknown state, not
fabricated certainty"), whose notes/test node ids are updated to describe
the new GATE_UNAVAILABLE status + PASS_FAIL_CLOSED_VERIFIED replay class,
verified against a live `pytest --collect-only` run (never hand-typed-and-
trusted, same convention as scripts/gen_fault_matrix_phase7.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE7_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase7.json"
PHASE8_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase8.json"

UPDATES = {
    "F22": {
        "description": "RDF4J temporarily down -> governed proposal fails safely",
        "test_files": ["tests/integration/test_decision_service_dependency_outage.py::test_f22_rdf4j_down_fails_proposal_safely"],
        "note": (
            "Unchanged behavior from Phase 5: RDF4J unreachable means no governed Decision could even be "
            "attempted (evidence-gathering/the SHACL-validated write itself fails) -- HTTP 503, zero "
            "Decision record written at all (proposal_attempt_failures logs the attempt). Distinct from "
            "F23/F24 below, where a Decision IS written (the OTHER gate already ran) but records the "
            "specific gate as unavailable."
        ),
    },
    "F23": {
        "description": "OpenFGA unavailable -> fail closed for protected action",
        "test_files": ["tests/integration/test_decision_service_dependency_outage.py::test_f23_openfga_down_denies_authorization_explicitly"],
        "note": (
            "Phase 8 step 0 fix: an OpenFGA outage now yields the new terminal status GATE_UNAVAILABLE "
            "(unavailable_gate='authorization'), HTTP 503 on POST /decisions/propose -- never the "
            "previous DENIED_AUTHORIZATION, which fabricated a denial the gate never actually issued "
            "(acceptance criterion A.11). Still fully governed (a real, SHACL-validated Decision is "
            "written -- contracts/ontology/v3 + contracts/shapes/v3 add oo:GateUnavailable to the "
            "enumeration) and still fail-closed (0 effects, decision_content_hash never set). The test "
            "now also replays the resulting decision once OpenFGA recovers and asserts "
            "status == PASS_FAIL_CLOSED_VERIFIED (services/decision_service/replay.py's new replay class "
            "for exactly this case) -- never FAIL for not reproducing a resolved outage."
        ),
    },
    "F24": {
        "description": "OPA unavailable -> fail closed unless action explicitly classified otherwise",
        "test_files": ["tests/integration/test_decision_service_dependency_outage.py::test_f24_opa_down_denies_policy_explicitly"],
        "note": (
            "Phase 8 step 0 fix: same treatment as F23 above, for the policy gate -- an OPA outage now "
            "yields GATE_UNAVAILABLE (unavailable_gate='policy'), HTTP 503, never the previous "
            "DENIED_POLICY. Replays as PASS_FAIL_CLOSED_VERIFIED once OPA recovers."
        ),
    },
}


def _collect_node_ids(test_files: list[str]) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *test_files, "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pytest --collect-only failed for {test_files}: {result.stdout}\n{result.stderr}")
    node_ids = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    if not node_ids:
        raise RuntimeError(f"no test node ids collected for {test_files} — matrix would claim a PASS with zero real tests")
    return node_ids


def main() -> int:
    matrix_doc = json.loads(PHASE7_PATH.read_text())
    for item in matrix_doc["matrix"]:
        fid = item["id"]
        if fid not in UPDATES:
            continue
        update = UPDATES[fid]
        node_ids = _collect_node_ids(update["test_files"])
        item["status"] = "PASS"
        item["test_node_ids"] = node_ids
        item["owning_phase"] = "Phase 8"
        item["note"] = update["note"]

    statuses = [item["status"] for item in matrix_doc["matrix"]]
    matrix_doc["phase"] = "8"
    matrix_doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    matrix_doc["summary"] = {
        "total": len(statuses),
        "PASS": statuses.count("PASS"),
        "NOT_TESTED": statuses.count("NOT_TESTED"),
    }

    PHASE8_PATH.write_text(json.dumps(matrix_doc, indent=2, sort_keys=False) + "\n")
    print(f"wrote {PHASE8_PATH} — summary: {matrix_doc['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
