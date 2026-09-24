#!/usr/bin/env python3
"""Phase 10b — the single comprehensive pytest run `make experiment` uses
to produce BOTH the mandatory test-results.json/junit xml
(docs/experiment/spec/13_repository_contract.md) AND the live evidence
scripts/gen_fault_results.py + scripts/gen_hypothesis_results.py derive
F01-F40 / H1-H14 status from — one real run, two consumers, never two
separately-timed runs that could silently disagree.

Covers every non-destructive mandatory + nightly-extended suite (spec 13
"CI gates" / "Nightly/local extended"): tests/model, tests/contracts,
tests/component, tests/integration, tests/faults, tests/replay,
tests/agent, tests/stateful. tests/ab is run SEPARATELY by
run_experiment.py's own AB step (the tests/ab -q CI-style gate immediately
followed by scripts/run_ab.py --w7-n 500 — the SAME sequence `make ab`
uses) so it is never run twice with two different sample sizes.
tests/mutation is also run separately (it toggles live process-wide state
— mutate.py — and must not interleave with anything else touching the
shared stack). tests/integration/test_seed_determinism.py
(test-destructive) is EXCLUDED — it resets the stack itself and must
never run inside this suite.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PY = str(REPO_ROOT / ".venv" / "bin" / "python")

SUITE_DIRS = [
    "tests/model", "tests/contracts", "tests/component", "tests/integration",
    "tests/faults", "tests/replay", "tests/agent", "tests/stateful",
]
IGNORE = ["tests/integration/test_seed_determinism.py"]


def run(results_dir: Path) -> dict:
    results_dir.mkdir(parents=True, exist_ok=True)
    junit_path = results_dir / "test-results.xml"
    args = [
        VENV_PY, "-m", "pytest", *SUITE_DIRS, "-q",
        *[f"--ignore={p}" for p in IGNORE],
        f"--junit-xml={junit_path}",
        "-o", "junit_family=xunit2",
    ]
    print(f"[run_full_test_suite] {' '.join(args)}", flush=True)
    t0 = time.monotonic()
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
    elapsed = round(time.monotonic() - t0, 1)
    print(proc.stdout[-8000:])
    if proc.returncode not in (0, 1):  # 1 == some tests failed, still a real result
        print(proc.stderr[-4000:], file=sys.stderr)

    summary = _parse_junit(junit_path) if junit_path.exists() else {"error": "no junit xml produced", "stdout_tail": proc.stdout[-4000:]}
    summary["elapsed_s"] = elapsed
    summary["pytest_exit_code"] = proc.returncode
    summary["command"] = " ".join(args)
    summary["stdout_summary_lines"] = [
        line for line in proc.stdout.splitlines()
        if any(tok in line for tok in (" passed", " failed", " error", " skipped"))
    ][-40:]

    (results_dir / "test-results.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def _parse_junit(junit_path: Path) -> dict:
    tree = ET.parse(junit_path)
    root = tree.getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    total = failures = errors = skipped = 0
    tests: dict[str, dict] = {}
    for suite in suites:
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.findall("testcase"):
            # pytest's own junit_family=xunit2 writer emits `classname` as
            # the DOTTED MODULE PATH with NO ".py" (e.g.
            # "tests.contracts.test_shacl_fixtures") and usually omits
            # `file` entirely — verified live (2026-09-24: grepping a real
            # junit-xml for `file="` found nothing). The curated fault
            # catalog (fault-matrix-phase10a.json) and every substring
            # match in gen_fault_results.py/gen_hypothesis_results.py
            # expect real file paths WITH ".py" — reconstruct that here,
            # once, at the source, rather than stripping ".py" from every
            # downstream matcher.
            file_attr = case.get("file")
            if file_attr:
                node_id = f"{file_attr}::{case.get('name')}"
            else:
                node_id = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name')}"
            outcome = "passed"
            message = None
            fail_el = case.find("failure")
            err_el = case.find("error")
            skip_el = case.find("skipped")
            if fail_el is not None:
                outcome, message = "failed", (fail_el.get("message") or fail_el.text or "")[:2000]
            elif err_el is not None:
                outcome, message = "error", (err_el.get("message") or err_el.text or "")[:2000]
            elif skip_el is not None:
                outcome, message = "skipped", (skip_el.get("message") or "")[:500]
            tests[node_id] = {"outcome": outcome, "message": message, "time_s": float(case.get("time", 0))}

    passed = total - failures - errors - skipped
    return {
        "junit_xml": str(junit_path.relative_to(REPO_ROOT)) if junit_path.is_relative_to(REPO_ROOT) else str(junit_path),
        "total": total, "passed": passed, "failed": failures, "errors": errors, "skipped": skipped,
        "tests": tests,
    }


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    summary = run(results_dir)
    print(json.dumps({k: v for k, v in summary.items() if k != "tests"}, indent=2, sort_keys=True))
    return 0 if summary.get("failed", 1) == 0 and summary.get("errors", 1) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
