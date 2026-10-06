#!/usr/bin/env python3
"""Evaluate an H18 evidence directory against the post-hoc weak H18 (H18w): writes verdict.json (verdict-h18w.json if a strong-H18 verdict.json is already there).

    .venv/bin/python scripts/evaluate_h18w.py <evidence-dir> [--no-write]
The strong-H18 verdict.json (scripts/evaluate_h18.py) is left alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from eoo_h18.evaluate_w import evaluate  # noqa: E402


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    d = Path(args[0])
    v = evaluate(d)
    if "--no-write" not in argv:
        out = d / "verdict.json"
        if out.exists() and json.loads(out.read_text()).get("hypothesis_id") != "H18w":
            out = d / "verdict-h18w.json"  # never overwrite the strong-H18 verdict
        out.write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v[k] for k in ("experiment_id", "hypothesis_id", "verdict", "common", "problems")}, indent=1))
    return 0 if v["verdict"] in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
