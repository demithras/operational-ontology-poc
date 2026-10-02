#!/usr/bin/env python3
"""Frozen H16 experiment run: writes round2/experiments/h16/<exp-id>/ (six evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h16.py --exp-id exp-h16-001 --seed 16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_exp.outdir import OutputExists  # noqa: E402
from eoo_h16 import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=json.loads((ROOT / "protocol/thresholds.json").read_text())["H16"]["min_generated_mixed_cases"],
                    help="unique mixed-domain packages (default: the frozen minimum)")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h16"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.n, Path(a.out_root), a.exp_id)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
