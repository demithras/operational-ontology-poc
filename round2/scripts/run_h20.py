#!/usr/bin/env python3
"""H20 experiment run: writes round2/experiments/h20/<exp-id>/ (five evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h20.py --exp-id exp-h20-dev --seed 20
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
from eoo_h20 import run as runner  # noqa: E402


def main() -> int:
    th = json.loads((ROOT / "hypotheses/h20/contract.json").read_text())["experiment"]["minimum_runs"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n-synth", type=int, default=(th * 12) // 10, help="unique synthetic definitions (default 1.2x the frozen minimum)")
    ap.add_argument("--n-machine", type=int, default=100, help="H17 state-machine examples per domain, traced")
    ap.add_argument("--n-probe", type=int, default=150, help="alias-invariance definitions per mutant")
    ap.add_argument("--suite", action="append", help="pytest target of the traced domain suites (default: tests/domains + tests/h18/test_git_store.py)")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h20"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.n_synth, Path(a.out_root), a.exp_id, a.n_machine, a.n_probe, a.suite)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
