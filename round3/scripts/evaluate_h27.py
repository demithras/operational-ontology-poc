#!/usr/bin/env python
"""Apply the H27 contract evaluator to experiments/h27/<exp-id>/ -> verdict.json (DualVerdict + hashes).
Variant directories with other names (test fakes) are evaluated too; paladin/conventional fill the dual-track slots."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h27.evaluator import evaluate_experiment  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_id")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h27"))
    ap.add_argument("--min-tampered", type=int, default=None, help="TEST ONLY: lowers the 5,000 tampered-case minimum")
    ap.add_argument("--min-bases-per-domain", type=int, default=None, help="TEST ONLY: lowers the 300 bases/domain minimum")
    ap.add_argument("--min-controls", type=int, default=None, help="TEST ONLY: lowers the 1,000 clean-control minimum")
    ap.add_argument("--print-only", action="store_true", help="do not write verdict.json (used by verify)")
    a = ap.parse_args()
    ov = (a.min_tampered, a.min_bases_per_domain, a.min_controls)
    if any(x is not None for x in ov) and "-dev" not in a.exp_id:
        print(f"refusing: minimum overrides are allowed only for dev experiment ids (containing '-dev'), not {a.exp_id!r}",
              file=sys.stderr)
        return 2
    exp = Path(a.out_root) / a.exp_id
    th = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
    res = evaluate_experiment(exp, th, *ov)
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
