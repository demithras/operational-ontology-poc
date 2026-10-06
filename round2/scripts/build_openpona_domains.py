#!/usr/bin/env python3
"""Render domains/<d>/ir.json to domains/<d>/openpona.op + openpona.record.json (H15 Phase 2).

--check: exit 1 if the committed files differ from a fresh render.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_openpona import dump_record, render  # noqa: E402

DOMAINS = ("manufacturing", "project")


def main() -> int:
    check = "--check" in sys.argv
    bad = 0
    for d in DOMAINS:
        ir = json.loads((ROOT / "domains" / d / "ir.json").read_text())
        text, rec = render(ir)
        files = {ROOT / "domains" / d / "openpona.op": text,
                 ROOT / "domains" / d / "openpona.record.json": dump_record(rec)}
        for path, content in files.items():
            if check:
                if not path.exists() or path.read_text() != content:
                    print(f"STALE {path.relative_to(ROOT)}")
                    bad += 1
            else:
                path.write_text(content)
                print(f"wrote {path.relative_to(ROOT)} ({len(content.splitlines())} lines)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
