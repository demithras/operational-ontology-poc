#!/usr/bin/env python
"""Apply the H25 contract evaluator to experiments/h25/<exp-id>/ -> verdict.json (DualVerdict + hashes)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h25.evaluator import evaluate_experiment  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_id")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h25"))
    ap.add_argument("--min-cases", type=int, default=None, help="DEV ONLY: lowers the minimum (all volume floors scale); never in thresholds")
    ap.add_argument("--print-only", action="store_true", help="do not write verdict.json (used by verify)")
    a = ap.parse_args()
    if (a.min_cases is not None) and "-dev" not in a.exp_id:
        print(f"refusing: --min-cases overrides frozen minimums and are allowed only for "
              f"dev experiment ids (containing '-dev'), not {a.exp_id!r}", file=sys.stderr)
        return 2
    exp = Path(a.out_root) / a.exp_id
    th = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
    res = evaluate_experiment(exp, th, a.min_cases)
    text = json.dumps(res, indent=1, sort_keys=True) + "\n"
    if a.print_only:
        sys.stdout.write(text)
    else:
        (exp / "verdict.json").write_text(text)
        print(json.dumps({k: res[k] for k in ("paladin_verdict", "conventional_verdict")}))
        for n, v in res["variants"].items():
            print(f"{n}: {v['verdict']} {v['reasons']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
