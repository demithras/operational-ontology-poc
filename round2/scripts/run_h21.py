#!/usr/bin/env python3
"""H21 experiment run: writes round2/experiments/h21/<exp-id>/ (six evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h21.py --exp-id exp-h21-dev --seed 21
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
from eoo_h21 import run as runner  # noqa: E402


def main() -> int:
    th = json.loads((ROOT / "hypotheses/h21/contract.json").read_text())["experiment"]["minimum_runs"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n-cases", type=int, default=(th * 12) // 10, help="unique principal cases PER DOMAIN (default 1.2x the frozen minimum)")
    ap.add_argument("--n-engine", type=int, default=1500, help="cases per domain cross-checked against the live Engine")
    ap.add_argument("--n-mutant-cases", type=int, default=1000)
    ap.add_argument("--n-fuzz", type=int, default=150, help="mangled tool-name calls per principal")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h21"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.n_cases, Path(a.out_root), a.exp_id, a.n_engine, a.n_mutant_cases, a.n_fuzz)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
