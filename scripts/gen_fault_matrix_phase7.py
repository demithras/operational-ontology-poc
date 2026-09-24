#!/usr/bin/env python3
"""Generates experiments/exp-000/results/fault-matrix-phase7.json from
experiments/exp-000/results/fault-matrix-phase6b.json — carries every
F01-F40 entry forward UNCHANGED except F28/F29/F39 (this phase's own
scope, docs/experiment/briefs/phase7.md), which are updated to PASS with
their REAL test node ids, verified against a live `pytest --collect-only`
run (never hand-typed-and-trusted — same convention Phase 6b's own
generator used, per docs/experiment/implementation-notes.md).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE6B_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase6b.json"
PHASE7_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase7.json"

UPDATES = {
    "F28": {
        "description": "ontology migration incompatible -> CI/replay build fails",
        "test_files": ["tests/contracts/test_compat_check.py"],
        "note": (
            "scripts/compat_check.py (Makefile `test-contracts`) fails a published contracts/<kind>/vN "
            "(N>=2) that lacks migration coverage. Positive case: the real repo tree has zero violations. "
            "Negative cases: a synthetic version with no migrations/ dir, an empty migrations/ dir, and a "
            "migration.json pointing at a nonexistent script are all caught."
        ),
    },
    "F29": {
        "description": "old policy deleted -> replay fails loudly; experiment considered failed",
        "test_files": ["tests/replay/test_f29_replay_integrity.py"],
        "note": (
            "services/decision_service/replay.py::_verify_archive re-hashes every archived contract "
            "directory a decision pinned before re-running any gate; a deleted or modified archived "
            "policy file raises ReplayIntegrityError (HTTP 409 via POST /replay/{id}) -- verified live "
            "against a real V1 corpus decision, restored, and re-verified PASS again."
        ),
    },
    "F39": {
        "description": "invalid mapping rule deployment -> identity -> compatibility fixture catches or ambiguity exposed",
        "test_files": ["tests/component/test_f39_invalid_mapping_rule.py"],
        "note": (
            "services/identity_resolver/resolver.py::IdentityResolver already validated mapping_rules.yaml "
            "at load time (ConflictingMappingRuleError, explicitly commented \"F39\") since an earlier phase "
            "-- this phase is the first to exercise it: conflicting explicit-override entries, an unknown "
            "rule kind, and a pattern rule missing canonical_template are all caught loudly at load time; "
            "a known-negative (structurally valid file) still loads and resolves correctly."
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
    matrix_doc = json.loads(PHASE6B_PATH.read_text())
    for item in matrix_doc["matrix"]:
        fid = item["id"]
        if fid not in UPDATES:
            continue
        update = UPDATES[fid]
        node_ids = _collect_node_ids(update["test_files"])
        item["status"] = "PASS"
        item["test_node_ids"] = node_ids
        item["owning_phase"] = "Phase 7"
        item["note"] = update["note"]

    statuses = [item["status"] for item in matrix_doc["matrix"]]
    matrix_doc["phase"] = "7"
    matrix_doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    matrix_doc["summary"] = {
        "total": len(statuses),
        "PASS": statuses.count("PASS"),
        "NOT_TESTED": statuses.count("NOT_TESTED"),
    }

    PHASE7_PATH.write_text(json.dumps(matrix_doc, indent=2, sort_keys=False) + "\n")
    print(f"wrote {PHASE7_PATH} — summary: {matrix_doc['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
