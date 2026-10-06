#!/usr/bin/env python3
"""Frozen H17 experiment run: writes round2/experiments/h17/<exp-id>/ (four evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h17.py --exp-id exp-h17-001 --seed 17
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
from eoo_h17 import run as runner  # noqa: E402


def main() -> int:
    th = json.loads((ROOT / "protocol/thresholds.json").read_text())["H17"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--per-domain", type=int, default=(th["min_state_machine_examples"] * 6) // 10,
                    help="unique state-machine traces per domain (default: 1.2x the frozen total minimum, split evenly)")
    ap.add_argument("--fn-traces", type=int, default=1800, help="function-only traces per domain")
    ap.add_argument("--control-examples", type=int, default=150)
    ap.add_argument("--mutant-examples", type=int, default=300)
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h17"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.per_domain, Path(a.out_root), a.exp_id, a.fn_traces, a.control_examples, a.mutant_examples)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
