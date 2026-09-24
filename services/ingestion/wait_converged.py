#!/usr/bin/env python3
"""`make wait-converged` / `make wait-connectors` entry point
(docs/experiment/briefs/phase4fix.md "A single readiness contract").

Blocks until services/ingestion/readiness.py's full convergence contract
is satisfied, printing progress as it goes, and prints exactly what is
still missing (never fakes success — common.md honesty rule) if the
timeout is hit.

Usage:
    .venv/bin/python services/ingestion/wait_converged.py             # full contract (post-seed)
    .venv/bin/python services/ingestion/wait_converged.py --no-data   # infra-only (post-up, pre-seed)
    .venv/bin/python services/ingestion/wait_converged.py --timeout 300

Phase 10b item 9: the 240s default timed out once right after a fresh
`reset + --build` in Phase 7b (a cold-start image rebuild adds real
minutes before the pipeline is even consuming). Configurable two ways —
CLI `--timeout` (highest precedence) or the `WAIT_CONVERGED_TIMEOUT_S` env
var (so `make wait-converged` itself can be budget-adjusted for a
clean-machine/cold-start run without editing the Makefile) — default
unchanged (240.0) for the common warm case. Actual convergence time is
always printed and returned so a caller (e.g. run_experiment.py's
clean-machine step) can record it rather than merely assume the budget
was enough.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.ingestion import readiness  # noqa: E402


def main() -> int:
    default_timeout = float(os.environ.get("WAIT_CONVERGED_TIMEOUT_S", "240.0"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-data", action="store_true", help="skip RDF4J fixture / projection checks (no seed run yet)")
    parser.add_argument("--timeout", type=float, default=default_timeout,
                         help=f"overall timeout in seconds for the Kafka-lag / fixture waits (default {default_timeout}, "
                              f"from WAIT_CONVERGED_TIMEOUT_S if set)")
    args = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    t0 = time.monotonic()
    try:
        readiness.wait_for_converged(expect_data=not args.no_data, timeout_s=args.timeout, log=log)
    except readiness.ConvergenceTimeout as e:
        elapsed = time.monotonic() - t0
        print(f"[wait-converged] TIMED OUT after {elapsed:.1f}s (budget was {args.timeout:.0f}s): {e}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - t0
    print(f"[wait-converged] converged in {elapsed:.1f}s (budget was {args.timeout:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
