#!/usr/bin/env python
"""List every A5(c) static-scan hit of a variant as JSON lines with its resolution key (G3-E24), for auditor review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h25 import audit  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=("paladin", "conventional"))
    ap.add_argument("--active-mutant", action="append", default=[], help="scan the build where this mutant is active")
    a = ap.parse_args()
    scan = audit.static_scan(pkg_dir=ROUND3 / "src" / a.variant, active_mutants=tuple(a.active_mutant))
    for status, rows in (("unresolved", scan["hits"]), ("resolved", scan["resolved"])):
        for h in rows:
            print(json.dumps({"status": status, "variant": a.variant, "file": h["file"], "line": h["line"], "kind": h["kind"],
                              "literal": h["literal"], "text": h["text"], "reason": h.get("reason"),
                              "key": list(audit.hit_key(a.variant, h))}, sort_keys=True))
    print(json.dumps({"summary": True, "variant": a.variant, "unresolved": scan["hit_count"], "resolved": scan["resolved_count"],
                      "domain_logic_modules": scan["domain_logic_modules"]}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
