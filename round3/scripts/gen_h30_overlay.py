#!/usr/bin/env python
"""Generate (or --check) the frozen H30 workload overlay files spec/gate6/workload-overlay/<domain>.json (PROT-H30 1.9).
usage: gen_h30_overlay.py [--out-dir DIR] [--check]       --check: regenerate in memory and compare bytes; exit 1 on any difference."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h30 import overlay_gen as G  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROUND3 / G.OUT_DIR))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    if a.check:
        bad = 0
        for d in G.DOMAINS:
            p = out / f"{d}.json"
            want = G.canon(G.build_overlay(d, ROUND3))
            if not p.is_file() or p.read_text() != want:
                print(f"DIFFERS: {p}")
                bad += 1
            else:
                print(f"ok: {p} ({G.sha(p)})")
        return 1 if bad else 0
    for p in G.write_all(ROUND3, out):
        print(f"wrote {p} sha256={G.sha(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
