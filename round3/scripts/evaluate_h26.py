#!/usr/bin/env python
"""Apply the H26 contract evaluator to experiments/h26/<exp-id>/ -> verdict.json (DualVerdict + hashes)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h26.evaluator import evaluate_experiment  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_id")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h26"))
    for k in ("min-pairs", "min-aa", "min-fuzz-calls", "min-per-kind", "min-per-channel", "min-probes"):
        ap.add_argument(f"--{k}", type=int, default=None, help="TEST ONLY (dev ids): lowers the minimum")
    ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args()
    ov = {k: getattr(a, k) for k in ("min_pairs", "min_aa", "min_fuzz_calls", "min_per_kind", "min_per_channel", "min_probes")}
    if any(v is not None for v in ov.values()) and "-dev" not in a.exp_id:
        print("refusing: minimum overrides are allowed only for dev experiment ids (containing '-dev')", file=sys.stderr)
        return 2
    exp = Path(a.out_root) / a.exp_id
    th = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
    res = evaluate_experiment(exp, th, ov)
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
