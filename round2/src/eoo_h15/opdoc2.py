"""Text-level helpers for the OpenPona v2 surface. v2 lines carry no labels, so the canonical form of a document is
simply every line with the atoms bound on it (line deletion is opdoc.delete_line: the record-key format is shared)."""
from __future__ import annotations

import json
import re

_KEY = re.compile(r"L([1-9][0-9]*)\.a([1-9][0-9]*)")


def line_atoms(rec: dict) -> dict[int, list]:
    out: dict[int, list] = {}
    for k in sorted(rec, key=lambda s: tuple(int(x) for x in _KEY.fullmatch(s).groups())):
        out.setdefault(int(_KEY.fullmatch(k).group(1)), []).append(rec[k])
    return out


def canonical_doc(text: str, rec: dict) -> str:
    atoms = line_atoms(rec)
    return "\n".join(f"{' '.join(ln.split())} || {json.dumps(atoms.get(n, []), ensure_ascii=False)}"
                     for n, ln in enumerate(text.splitlines(), 1))
