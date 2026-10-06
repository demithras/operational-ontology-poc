#!/usr/bin/env python3
"""Evaluate an H15 evidence directory: writes verdict.json and REPORT.md next to the evidence.

    .venv/bin/python scripts/evaluate_h15.py round2/experiments/h15/exp-h15-001 [--no-write]
    .venv/bin/python scripts/evaluate_h15.py <dir> [--surface openpona2] [--candidate-pin PATH] [--no-write]

The surface is read from the evidence records (candidate_surface; absent = the v1 candidate 'openpona'); --surface
only asserts it. v2 evidence is judged by eoo_h15.evaluate_v2 (protocol/H15_V2_PREREG.json); --candidate-pin overrides
the v2 pin file (default protocol/H15_V2_CANDIDATE.json, e.g. for a development run).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_h15 import evaluate_v2  # noqa: E402
from eoo_h15.evaluate import evaluate  # noqa: E402
from eoo_h15.report import render_report  # noqa: E402


def _opt(argv: list[str], name: str):
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main(argv: list[str]) -> int:
    pin, want = _opt(argv, "--candidate-pin"), _opt(argv, "--surface")
    skip = {pin, want}
    args = [a for a in argv if not a.startswith("--") and a not in skip]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    d = Path(args[0])
    surface = evaluate_v2.evidence_surface(d)
    if want and want != surface:
        print(f"REFUSED: evidence was produced by surface {surface!r}, not {want!r}", file=sys.stderr)
        return 2
    v = evaluate_v2.evaluate(d, candidate_pin=pin) if surface == "openpona2" else evaluate(d)
    if "--no-write" not in argv:
        (d / "verdict.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
        (d / "REPORT.md").write_text(render_report(d, v))
    print(json.dumps({k: v[k] for k in ("experiment_id", "verdict", "common", "problems")}, indent=1))
    return 0 if v["verdict"] in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
