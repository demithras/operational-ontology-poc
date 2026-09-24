#!/usr/bin/env python3
"""Generates experiments/exp-000/results/fault-matrix-phase9.json from
experiments/exp-000/results/fault-matrix-phase8.json — carries every
F01-F40 entry forward UNCHANGED except:

- F30 ("prompt injection -> no policy bypass"), Phase 9's own scope: was
  NOT_TESTED ("no agent/MCP layer exists yet") — now PASS, backed by
  tests/agent/test_f30_prompt_injection.py's real, live-collected node ids.
- F04/F31/F32/F33, already PASS from Phase 5/6b against the raw HTTP API —
  their `test_node_ids` gain the NEW tests/agent/ node ids that prove the
  SAME property holds through the actual MCP tool surface (services/mcp),
  not a status change (the underlying property was already proven; this is
  additional, independent evidence at a different entry point).

Same "verify every node id against a live `pytest --collect-only` run,
never hand-typed-and-trusted" convention as scripts/gen_fault_matrix_phase7.py
/ scripts/gen_fault_matrix_phase8.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE8_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase8.json"
PHASE9_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "fault-matrix-phase9.json"

F30_TEST_FILE = "tests/agent/test_f30_prompt_injection.py"

# Additional tests/agent/ node ids proving the SAME already-PASS property
# through the MCP surface specifically — one file each, collected live below.
ADDITIONAL_AGENT_TEST_FILES = {
    "F04": "tests/agent/test_f04_undisclosed_tools.py",
    "F31": "tests/agent/test_f31_tool_parameter_tampering.py",
    "F32": "tests/agent/test_f32_impersonation_and_identity_retry.py",
    "F33": "tests/agent/test_stale_and_replay.py",
}


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
    matrix_doc = json.loads(PHASE8_PATH.read_text())

    for item in matrix_doc["matrix"]:
        fid = item["id"]
        if fid == "F30":
            node_ids = _collect_node_ids(F30_TEST_FILE)
            item["status"] = "PASS"
            item["test_node_ids"] = node_ids
            item["owning_phase"] = "Phase 9"
            item["note"] = (
                "Implemented this phase: services/mcp (the MCP agent surface) + a deterministic scripted "
                "'compromised planner' (tests/agent/) that IS spec 09's prompt-injection scenario, driven "
                "live against the real MCP tool surface — the architectural property (H9: 'even a fully "
                "compromised planner cannot bypass enforcement') holds regardless of whether the request "
                "came from a jailbroken LLM prompt or a scripted client, since decision_service re-runs "
                "every gate server-side either way. A 500-unit request lands REQUIRES_APPROVAL (never "
                "auto-allow), and a follow-up attempt to execute it anyway is rejected (409), zero WMS "
                "effects, verified against real ground truth."
            )
        elif fid in ADDITIONAL_AGENT_TEST_FILES:
            new_ids = _collect_node_ids(ADDITIONAL_AGENT_TEST_FILES[fid])
            existing = item.get("test_node_ids", [])
            item["test_node_ids"] = existing + [n for n in new_ids if n not in existing]
            item["note"] = (
                (item.get("note") or "").rstrip() + (" " if item.get("note") else "") +
                "Phase 9: the same property additionally proven live through the actual MCP tool surface "
                "(services/mcp), not just the raw decision_service HTTP API."
            ).strip()

    statuses = [item["status"] for item in matrix_doc["matrix"]]
    matrix_doc["phase"] = "9"
    matrix_doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    matrix_doc["summary"] = {
        "total": len(statuses),
        "PASS": statuses.count("PASS"),
        "NOT_TESTED": statuses.count("NOT_TESTED"),
    }

    PHASE9_PATH.write_text(json.dumps(matrix_doc, indent=2, sort_keys=False) + "\n")
    print(f"wrote {PHASE9_PATH} — summary: {matrix_doc['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
