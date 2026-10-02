#!/usr/bin/env python3
"""Evaluate an H20 evidence directory: writes verdict.json next to the evidence.

    .venv/bin/python scripts/evaluate_h20.py round2/experiments/h20/exp-h20-dev [--no-write]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from eoo_h20.evaluate import evaluate  # noqa: E402


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    d = Path(args[0])
    v = evaluate(d)
    if "--no-write" not in argv:
        (d / "verdict.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v[k] for k in ("experiment_id", "verdict", "common", "problems")}, indent=1))
    return 0 if v["verdict"] in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
