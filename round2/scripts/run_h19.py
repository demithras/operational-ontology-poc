#!/usr/bin/env python3
"""Frozen H19 experiment run: writes round2/experiments/h19/<exp-id>/ (five evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h19.py --exp-id exp-h19-001 --seed 19
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
from eoo_h19 import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=json.loads((ROOT / "hypotheses/h19/contract.json").read_text())["experiment"]["minimum_runs"],
                    help="unique concurrency scenarios (default: the contract minimum_runs)")
    ap.add_argument("--audit-cases", type=int, default=600, help="Engine-level lifecycle cases for the canonical-change audit")
    ap.add_argument("--mutation-scenarios", type=int, default=400)
    ap.add_argument("--mutation-audit-cases", type=int, default=40)
    ap.add_argument("--ir-version", default=None, help="Project contract version (default: the pack default, v3)")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h19"))
    a = ap.parse_args()
    try:
        info = runner.run(a.seed, a.n, Path(a.out_root), a.exp_id, a.audit_cases, a.mutation_scenarios, a.mutation_audit_cases, log=lambda m: print(m, flush=True), ir_version=a.ir_version)
    except OutputExists as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote {Path(a.out_root) / a.exp_id} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
