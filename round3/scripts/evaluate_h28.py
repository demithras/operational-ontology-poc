#!/usr/bin/env python
"""Apply the H28 contract evaluator to experiments/h28/<exp-id>/ -> verdict.json. Dev size overrides are read from each variant's
manifest (stamped at run time); the evaluator marks them INVALID on a non-dev id."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h28.evaluator import evaluate_experiment  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_id", metavar="EXP", help="an experiment id (resolved under --out-root) OR a path to an experiment directory "
                    "(anything containing '/', e.g. experiments/h28/exp-h28-001); with a path, --out-root is ignored")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h28"))
    ap.add_argument("--print-only", action="store_true", help="do not write verdict.json (used by verify)")
    a = ap.parse_args()
    exp = Path(a.exp_id).resolve() if "/" in a.exp_id else Path(a.out_root) / a.exp_id
    if not exp.is_dir():
        print(f"no such experiment: {exp}", file=sys.stderr)
        return 2
    res = evaluate_experiment(exp, json.loads((ROUND3 / "protocol" / "thresholds.json").read_text()))
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
