#!/usr/bin/env python3
"""`make experiment` (docs/experiment/spec/13_repository_contract.md) —
Phase 10b. Creates a NEW immutable experiments/exp-NNN/ (manifest.yaml
copying exp-000's LOCKED thresholds unchanged, seeds.txt) and runs the
full, real, live pipeline: the fair evolution comparison (item 7 — this
step performs its OWN destructive fresh reset, `OO_ALLOW_DESTRUCTIVE=1`,
so real V1 SHACL shapes are genuinely live while V1-era history is built;
see scripts/gen_evolution_comparison.py's own docstring for why a
pointer-only shortcut was tried and rejected), the
full 5,000-decision bulk corpus for both variants (item 4), the
comprehensive test suite + mutation tests, the full A/B rerun (W1-W7 at
N=500), latency benchmarks (incl. H13 forensic query timing), the fault
matrix (derived from the same test run), then derives hypothesis-results
.json and final-report.md from the real artifacts this run produced.

Prints `STEP N: <name>` before each stage and `DONE`/`ABORT` at the end —
this script is meant to be launched detached (nohup) with output
redirected to a log file; a caller polls for the final marker, never the
intermediate steps.

Exit code follows docs/experiment/spec/11_acceptance_criteria.md (also
mirrored by scripts/gen_acceptance_verdict.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
VENV_PY = str(REPO_ROOT / ".venv" / "bin" / "python")
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
EXP000_RESULTS = EXPERIMENTS_DIR / "exp-000" / "results"

RAW_ARTIFACTS_TO_COPY = [
    "bench-phase4.json", "bench-phase5.json", "bench-phase6.json",
    "mutation-results.json", "historical-corpus.json", "historical-corpus-baseline.json",
    "baseline-replay-sweep.json", "evolution-comparison.json",
    "ab-tradeoffs.md", "traces-reference.txt", "agent-llm-probe.json",
]


def _next_exp_dir() -> Path:
    existing = sorted(p.name for p in EXPERIMENTS_DIR.glob("exp-*") if p.is_dir())
    nums = [int(n.split("-")[1]) for n in existing if n.split("-")[1].isdigit()]
    return EXPERIMENTS_DIR / f"exp-{(max(nums) + 1):03d}"


def _step(n: int, name: str) -> None:
    print(f"\nSTEP {n}: {name}  [{time.strftime('%H:%M:%S')}]", flush=True)


def _run(args: list[str], allow_fail: bool = False, timeout: int = 3600) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(args)}", flush=True)
    proc = subprocess.run(args, cwd=REPO_ROOT, timeout=timeout)
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(f"command failed (exit {proc.returncode}): {' '.join(args)}")
    return proc


def main() -> int:
    exp_dir = _next_exp_dir()
    results_dir = exp_dir / "results"
    results_dir.mkdir(parents=True)
    exp_version = exp_dir.name
    print(f"[run_experiment] creating {exp_dir}", flush=True)

    _step(1, "copy locked manifest.yaml (thresholds unchanged) + seeds.txt")
    manifest_text = (EXPERIMENTS_DIR / "exp-000" / "manifest.yaml").read_text()
    manifest_text = manifest_text.replace('experiment_version: exp-000', f'experiment_version: {exp_version}')
    manifest_text = manifest_text.replace('status: LOCKED', f'status: LOCKED  # copied unchanged from exp-000 per spec 01 preamble')
    (exp_dir / "manifest.yaml").write_text(manifest_text)
    (exp_dir / "seeds.txt").write_text("SEED=42\n")

    _step(2, "fair evolution comparison (item 7) — its OWN destructive fresh reset (real V1 shapes live) -> "
             "V1 corpus -> deploy V2 -> V2 corpus -> deploy V3 -> full replay sweep, both variants. Every "
             "later step in this run operates on the stack THIS step produces, not the one `make test` "
             "validated earlier in the clean-machine sequence.")
    from scripts import gen_evolution_comparison
    gen_evolution_comparison.main()

    _step(3, "full 5,000-decision bulk corpus, both variants (item 4)")
    _run([VENV_PY, "seed/generators/bulk_historical_decisions.py", "--target", "5000", "--seed", "42"], timeout=1800)
    _run([VENV_PY, "seed/generators/bulk_historical_decisions_baseline.py", "--target", "5000", "--seed", "42"], timeout=1800)

    _step(4, "comprehensive test suite (model/contracts/component/integration/faults/replay/agent/stateful/ab-gate)")
    from scripts import run_full_test_suite
    run_full_test_suite.run(results_dir)

    _step(5, "mutation tests (spec 08) — re-run fresh for this experiment's own evidence")
    mutation_proc = subprocess.run([VENV_PY, "-m", "pytest", "tests/mutation", "-q"], cwd=REPO_ROOT, timeout=1200)
    print(f"  mutation suite exit={mutation_proc.returncode}")

    _step(6, "full A/B rerun: W1-W7 at N=500, both variants (item 4)")
    _run([VENV_PY, "-m", "pytest", "tests/ab", "-q"], allow_fail=True, timeout=600)
    _run([VENV_PY, "scripts/run_ab.py", "--w7-n", "500"], timeout=3600)
    _run([VENV_PY, "scripts/baseline_replay_sweep.py"], allow_fail=True, timeout=1800)
    _run([VENV_PY, "scripts/gen_ab_tradeoffs.py"], timeout=300)

    _step(7, "fault matrix (derived from step 4's own live test outcomes)")
    from scripts import gen_fault_results
    gen_fault_results.generate(results_dir)

    _step(8, "latency benchmarks: make bench + H13 forensic query timing on the full corpus (items 3/8)")
    _run([VENV_PY, "tests/performance/bench_phase4.py"], allow_fail=True, timeout=300)
    _run([VENV_PY, "tests/performance/bench_phase5.py"], allow_fail=True, timeout=300)
    _run([VENV_PY, "tests/performance/bench_phase6.py"], allow_fail=True, timeout=300)
    from scripts import gen_latency_report
    gen_latency_report.generate(results_dir, h13_sample_n=30)

    _step(9, "environment.json + contract-manifest.json")
    from scripts import gen_experiment_metadata
    gen_experiment_metadata.gen_environment(results_dir)
    gen_experiment_metadata.gen_contract_manifest(results_dir)

    _step(10, "traces-reference.txt (F40 evidence)")
    _run([VENV_PY, "scripts/gen_traces_reference.py"], allow_fail=True, timeout=120)

    _step(11, "copy raw supporting artifacts into the immutable exp results/ snapshot")
    for name in RAW_ARTIFACTS_TO_COPY:
        src = EXP000_RESULTS / name
        if src.exists():
            shutil.copy2(src, results_dir / name)
        else:
            print(f"  (missing, skipped: {name})")
    ab_src = EXP000_RESULTS / "ab-results.json"
    if ab_src.exists():
        shutil.copy2(ab_src, results_dir / "ab-results.json")

    _step(12, "derive hypothesis-results.json from this run's own evidence")
    from scripts import gen_hypothesis_results
    gen_hypothesis_results.derive(results_dir, exp_version)

    _step(13, "final-report.md + acceptance verdict + exit code")
    from scripts import gen_final_report
    gen_final_report.generate(results_dir, exp_version)
    verdict = json.loads((results_dir / "acceptance-verdict.json").read_text())

    print(f"\n[run_experiment] {exp_version}: can_decide_now={verdict['can_decide_now']} "
          f"can_prove_why_later={verdict['can_prove_why_later']} exit_code={verdict['exit_code']}")
    print(f"[run_experiment] results: {results_dir}")
    print("DONE" if verdict["exit_code"] == 0 else f"DONE (non-zero exit, see final-report.md): exit_code={verdict['exit_code']}")
    return verdict["exit_code"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - report ABORT before dying, per this repo's pipeline convention
        print(f"\nABORT: {type(exc).__name__}: {exc}", flush=True)
        raise
