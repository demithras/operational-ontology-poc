#!/usr/bin/env python3
"""Generate ontology/openpona2_encoding.md from the frozen v2 phrase table (src/eoo_openpona2). --check: exit 1 if stale."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eoo_openpona2.phrases import T, TYPE_GLOSS  # noqa: E402
from eoo_openpona2.table import expand, rule_line_counts, table_size  # noqa: E402
from eoo_openpona2.vocab import RESOURCE_HEADS, ROLES  # noqa: E402
from openpona2_encoding_prose import HEAD, TAIL  # noqa: E402

OUT = ROOT / "ontology" / "openpona2_encoding.md"
ROLE_NAME = {"pkg": "package id", "imp": "import string", "decl": "declared id", "subj": "subject id",
             "ctx": "context owner id", "prop": "property name", "param": "parameter name", "ni": "literal"}


def slot_roles(rid: str) -> str:
    _, e = expand(rid)[0]
    out = []
    for p in e.parts:
        if p.kind == "lit" or p.n == 0:
            continue
        if p.kind == "val":
            out.append(f"value ({p.arg})")
        elif p.kind == "ref":
            out.append(f"ref:{p.arg[0]} target" + (" (+ owner/import if qualified)" if "ext" in ROLES[p.arg[0]] else ""))
        elif p.kind == "type":
            out.append("ref-type target")
        else:
            out.append(ROLE_NAME[p.kind])
    return "; ".join(f"a{i}: {r}" for i, r in enumerate(out, 1)) or "none"


def esc(s: str) -> str:
    return s.replace("|", "\\|")


def build() -> str:
    counts = rule_line_counts()
    L = [HEAD.replace("{size}", str(table_size())), "## 6. Phrase table (one row per IR structural value / construct)", "",
         "`lines` = concrete lines the row licenses (alternative heads / reference forms / type phrases). Example = the "
         "row's first concrete line (it parses RESOLVED; atoms live in the record).", "",
         "| rule | IR path / meaning | pattern | slots (left to right) | canon gloss justification | strength | lines | example |",
         "|---|---|---|---|---|---|---|---|"]
    for rid, (pat, meaning, gloss, strength) in T.items():
        L.append(f"| `{rid}` | {esc(meaning)} | `{pat}` | {esc(slot_roles(rid))} | {esc(gloss)} | {strength} | "
                 f"{counts[rid]} | `{expand(rid)[0][0]}` |")
    L += ["", f"Total: {len(T)} rows, {table_size()} concrete lines.", "", "## 7. Type phrases (fillers of `{TYPE}`)", "",
          "| IR type | phrase | gloss justification | strength |", "|---|---|---|---|"]
    for t, (ph, gloss, strength) in TYPE_GLOSS.items():
        L.append(f"| `{t}` | `{ph}` | {esc(gloss)} | {strength} |")
    L += ["", "## 8. Heads and reference roles", "", "| head | kind |", "|---|---|"]
    L += [f"| `{h} ni` | {k} |" for h, k in RESOURCE_HEADS.items()]
    L += ["| `sona ni` | a property (in its owner's context) |", "| `kute ni` | a parameter (in its owner's context) |",
          "| `kulupu ni` | the package itself (pkg.decl) or an imported package |", "",
          "| reference role | written as |", "|---|---|"]
    for role, alts in ROLES.items():
        forms = ", ".join("`weka ni pi kulupu ni`" if a == "ext" else f"`sona ni pi {a[5:]} ni`" if a.startswith("prop:")
                          else f"`{a} ni`" for a in alts)
        L.append(f"| `{role}` | {forms} |")
    weak = [(rid, T[rid][0]) for rid in T if T[rid][3] == "weak"]
    L += ["", "## 9. Weak glosses and the meaning rule", "", "Weak glosses (judgment calls, listed for review):", ""]
    L += [f"- `{rid}`: `{pat}`" for rid, pat in weak]
    L += [f"- type `{t}` = `{ph}`" for t, (ph, _, s) in TYPE_GLOSS.items() if s == "weak"]
    L += ["", f"Meaning rule (machine check, `src/eoo_h15/meaning.py`): a rendered line is accepted only if it is one of "
          f"the {table_size()} concrete lines above, so the number of distinct phrases of any package, of any size, is at "
          "most the table size. No row exists to tell resources apart: the only words that vary between two resources "
          "of the same kind are none (their ids are record atoms). The bounded-vocabulary test reports the per-size "
          "counts; the v1 encoding fails the same test (known-negative, tests/h15/test_openpona2_meaning.py).", "", TAIL]
    return "\n".join(L)


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"STALE {OUT.relative_to(ROOT)}")
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
