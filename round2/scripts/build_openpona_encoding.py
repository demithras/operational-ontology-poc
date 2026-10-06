#!/usr/bin/env python3
"""Generate ontology/openpona_encoding.md from src/eoo_openpona/templates.py (single source of truth).

Example lines are real renders of tests/h15/openpona_coverage_ir.json (+ a tiny empty package), so
every example is a line the renderer emits and the compiler accepts. --check: exit 1 if stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eoo_openpona import render  # noqa: E402
from eoo_openpona.lines import read_line  # noqa: E402
from eoo_openpona.templates import ROLES, T, TYPE_GLOSS  # noqa: E402
from eoo_openpona.vocab import ALL_HEADS  # noqa: E402
from openpona_encoding_prose import FOOTER, HEADER  # noqa: E402

OUT = ROOT / "ontology" / "openpona_encoding.md"
EMPTY = {"package_id": "e", "version": "1", "imports": [], "object_types": [], "link_types": [], "interfaces": [],
         "functions": [], "actions": [], "policies": [], "authority_rules": [], "observation_types": [],
         "constraints": [], "metadata": {}}


def examples() -> dict[str, str]:
    cov = json.loads((ROOT / "tests" / "h15" / "openpona_coverage_ir.json").read_text())
    ex: dict[str, str] = {}
    for ir in (cov, EMPTY):
        text, _ = render(ir)
        for i, ln in enumerate(text.splitlines(), 1):
            ex.setdefault(read_line(i, ln).tid, ln)
    missing = set(T) - set(ex)
    if missing:
        raise SystemExit(f"no example line for templates {sorted(missing)}")
    return ex


def build() -> str:
    ex = examples()
    rows = ["| rule | IR path / meaning | line pattern | canon gloss justification | strength | example (parses RESOLVED) |",
            "|---|---|---|---|---|---|"]
    for tid, (pat, meaning, gloss, strength) in T.items():
        rows.append(f"| `{tid}` | {meaning} | `{pat}` | {gloss} | {strength} | `{ex[tid]}` |")
    types = ["| IR type | phrase | gloss justification | strength |", "|---|---|---|---|"]
    for k, (ph, why, st) in TYPE_GLOSS.items():
        types.append(f"| `{k}` | `{ph}` | {why} | {st} |")
    types.append("| `{list: T}` / `{optional: T}` | a type-node address (rules `type.list`, `type.optional`) | see those rows | strong |")
    heads = ["| head | stands for |", "|---|---|"] + [f"| `{h}` | {w} |" for h, w in ALL_HEADS.items()]
    roles = ["| reference role | heads allowed |", "|---|---|"] + [f"| `{r}` | {', '.join(f'`{h}`' for h in hs)} |"
                                                                for r, hs in ROLES.items()]
    weak = [f"- `{tid}`: {T[tid][1]} (`{T[tid][0]}`)" for tid in T if T[tid][3] == "weak"]
    weak += [f"- type `{k}` = `{v[0]}`" for k, v in TYPE_GLOSS.items() if v[2] == "weak"]
    return "\n".join([HEADER, "## 4. Address heads", "", *heads, "", "## 5. Reference roles", "", *roles, "",
                      "## 6. Line rules (one row per IR structural value / construct)", "", *rows, "",
                      "## 7. Type phrases", "", *types, "", "## 8. Weak glosses (judgment calls, listed for review)", "",
                      *weak, "", FOOTER])


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"STALE {OUT.relative_to(ROOT)}")
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
