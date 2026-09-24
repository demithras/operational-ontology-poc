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
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.ingestion import readiness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-data", action="store_true", help="skip RDF4J fixture / projection checks (no seed run yet)")
    parser.add_argument("--timeout", type=float, default=240.0, help="overall timeout in seconds for the Kafka-lag / fixture waits")
    args = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    try:
        readiness.wait_for_converged(expect_data=not args.no_data, timeout_s=args.timeout, log=log)
    except readiness.ConvergenceTimeout as e:
        print(f"[wait-converged] TIMED OUT: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
