#!/usr/bin/env python3
"""Frozen H15 experiment run: writes round2/experiments/h15/<exp-id>/ (six evidence files). Refuses to overwrite.

    .venv/bin/python scripts/run_h15.py --exp-id exp-h15-001 --seed 15
    .venv/bin/python scripts/run_h15.py --surface openpona2 --exp-id exp-h15-v2-001 --seed 15   # H15 v2

--surface picks the candidate (default openpona = v1). openpona2 needs a v2 candidate pin: protocol/H15_V2_CANDIDATE.json
(written with scripts/h15_v2_candidate.py --write), or --candidate-pin PATH for a development run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_h15 import candidate  # noqa: E402
from eoo_h15 import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=json.loads((ROOT / "protocol/thresholds.json").read_text())["H15"]["min_generated_valid_cases"],
                    help="generated cases (default: the frozen minimum)")
    ap.add_argument("--out-root", default=str(ROOT / "experiments/h15"))
    ap.add_argument("--surface", choices=sorted(candidate.CANDIDATES), default="openpona")
    ap.add_argument("--candidate-pin", default=None, help="v2 only: candidate pin file (default protocol/H15_V2_CANDIDATE.json)")
    a = ap.parse_args()
    if a.candidate_pin and a.surface != "openpona2":
        ap.error("--candidate-pin applies to --surface openpona2 only")
    candidate.use(a.surface, a.candidate_pin)
    out = Path(a.out_root) / a.exp_id
    if out.exists():
        print(f"REFUSED: {out} exists (experiments are immutable; use a new --exp-id)", file=sys.stderr)
        return 2
    tmp = out.with_name("." + out.name + ".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    info = runner.run(a.seed, a.n, tmp, a.exp_id)
    os.rename(tmp, out)
    print(f"wrote {out} ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
