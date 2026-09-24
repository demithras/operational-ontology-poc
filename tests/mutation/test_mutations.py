"""Phase 10a item 2 — docs/experiment/spec/08_test_strategy.md "Mutation
testing (recommended)": the 5 named mutation categories, applied to the
REAL running implementation (never a copy/sandbox), each proved to turn
its relevant suite RED on a real ASSERTION (not a setup/connection error —
this file reads the actual failure reason, per common.md's own "read the
failure reason" discipline), paired with a CONTROL that must stay GREEN
throughout, then reverted and reconfirmed clean.

Deliberately NOT part of `make test` (same family as test-faults/
test-destructive — docs/experiment/briefs/phase10a.md's common.md rules:
"one stack-touching command at a time", never overlapping runs). Each test
function drives its own apply -> target(RED) -> control(GREEN) -> revert ->
target(GREEN again) cycle via `scripts/mutate.py`, invoking the target/
control pytest node ids as REAL subprocesses (this file must not import
and re-run their assertions itself — that would test THIS file's copy of
the logic, not the real suite) and records the outcome into
`experiments/exp-000/results/mutation-results.json`.

Requires the full stack (`make up`, ideally `make seed`) reachable —
self-skips otherwise. Run alone: `.venv/bin/python -m pytest tests/mutation -q -s`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts import mutate  # noqa: E402
from seed import db_env  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "mutation-results.json"

_results: list[dict] = []


def _stack_up() -> bool:
    db_env.load_dotenv()
    try:
        r = httpx.get(f"{db_env.decision_service_url()}/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _stack_up(), reason="decision_service not reachable — run 'make up' first")


def _run_pytest(node_ids: list[str], timeout: float = 180.0) -> tuple[bool, str]:
    """Returns (all_passed, combined_output). Runs as a REAL subprocess
    against the actual test files on disk — never imports/re-executes their
    logic in-process."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *node_ids, "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )
    output = result.stdout + "\n" + result.stderr
    return result.returncode == 0, output


_SUMMARY_FAILED_RE = re.compile(r"(\d+) failed")
_SUMMARY_ERROR_RE = re.compile(r"(\d+) error")


def _is_red_on_assertion(output: str) -> bool:
    """Distinguishes a genuine assertion-level failure (pytest's own final
    summary line: "N failed") from a setup/collection/connection ERROR
    ("N error"), which would mean the mutation broke test SETUP rather than
    the behavior under test — not what this suite is trying to prove.
    Reads pytest's OWN summary counts (never the tail alone), per
    common.md's "read the failure reason" / "read every summary line"
    discipline, plus a direct AssertionError check as a second signal."""
    failed_match = _SUMMARY_FAILED_RE.search(output)
    error_match = _SUMMARY_ERROR_RE.search(output)
    n_failed = int(failed_match.group(1)) if failed_match else 0
    n_error = int(error_match.group(1)) if error_match else 0
    return n_failed > 0 and n_error == 0 and "AssertionError" in output


def _record(mutation_id: str, **fields) -> None:
    _results.append({"mutation_id": mutation_id, **fields})


def _run_one_mutation(mutation_id: str) -> None:
    m = mutate.MUTATIONS[mutation_id]
    record = {"description": m.description, "target": m.target, "control": m.control}
    try:
        mutate.apply_mutation(mutation_id)
        applied = True

        target_passed, target_output = _run_pytest(m.target)
        red_on_assertion = (not target_passed) and _is_red_on_assertion(target_output)
        record["target_went_red_on_assertion"] = red_on_assertion
        record["target_output_tail"] = target_output[-1500:]

        control_passed, control_output = _run_pytest(m.control)
        record["control_stayed_green"] = control_passed
        record["control_output_tail"] = control_output[-800:] if not control_passed else None
    finally:
        mutate.revert_mutation(mutation_id)
        applied = False
        record["reverted"] = True

    target_clean_passed, target_clean_output = _run_pytest(m.target)
    record["target_green_after_revert"] = target_clean_passed
    if not target_clean_passed:
        record["target_clean_output_tail"] = target_clean_output[-1500:]

    _record(mutation_id, **record)

    assert record["target_went_red_on_assertion"], (
        f"{mutation_id}: target suite did NOT go red on a genuine assertion failure while mutated.\n"
        f"Output tail:\n{record['target_output_tail']}"
    )
    assert record["control_stayed_green"], (
        f"{mutation_id}: control suite did NOT stay green while the mutation was active.\n"
        f"Output tail:\n{record.get('control_output_tail')}"
    )
    assert record["target_green_after_revert"], (
        f"{mutation_id}: target suite did NOT return to green after revert — revert is incomplete.\n"
        f"Output tail:\n{record.get('target_clean_output_tail')}"
    )


def test_mutation_policy_comparator():
    _run_one_mutation("POLICY_COMPARATOR")


def test_mutation_shacl_cardinality():
    _run_one_mutation("SHACL_CARDINALITY")


def test_mutation_authz_relation():
    _run_one_mutation("AUTHZ_RELATION")


def test_mutation_reconciliation_quantity():
    _run_one_mutation("RECONCILIATION_QUANTITY")


def test_mutation_idempotency_handling():
    _run_one_mutation("IDEMPOTENCY_HANDLING")


def test_zzz_write_results():
    """Runs last (pytest collects/executes in file order by default; "zzz"
    keeps this after the 5 mutation tests above regardless) — writes
    whatever landed in `_results` even if an earlier mutation test failed,
    so a partial run's evidence is never silently lost."""
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps({"mutations": _results}, indent=2, sort_keys=True) + "\n")
    print(f"wrote {RESULTS_PATH.relative_to(REPO_ROOT)} ({len(_results)} mutation records)")
