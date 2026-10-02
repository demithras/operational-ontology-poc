#!/usr/bin/env python3
"""H22 experiment run: writes round2/experiments/h22/<exp-id>/ (seven evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h22.py --exp-id exp-h22-dev --seed 21
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
from eoo_h22 import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h22"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, Path(a.out_root), a.exp_id)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
