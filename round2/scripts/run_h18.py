#!/usr/bin/env python3
"""Frozen H18 experiment run: writes round2/experiments/h18/<exp-id>/ (six evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h18.py --exp-id exp-h18-001 --seed 18
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from eoo_exp.outdir import OutputExists  # noqa: E402
from eoo_h18 import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=json.loads((ROOT / "hypotheses/h18/contract.json").read_text())["experiment"]["minimum_runs"],
                    help="unique lifecycle cases (default: the contract minimum_runs)")
    ap.add_argument("--mutation-cases", type=int, default=200)
    ap.add_argument("--ir-version", default="v2", help="Project contract version; v2 (default) reproduces exp-h18-001, v3 is the H18w candidate")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h18"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.n, Path(a.out_root), a.exp_id, a.mutation_cases, log=lambda m: print(m, flush=True), ir_version=a.ir_version)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
