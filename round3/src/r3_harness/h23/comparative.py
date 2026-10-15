"""Comparative-record fields of protocol/DUAL_TRACK.json that come from the source tree (LOC, components).

security_specific_loc = non-blank, non-comment Python LOC of src/<variant>: {"total": N, "excluding_vendored_unchanged": M}.
M excludes files listed in src/<variant>/VENDORED.json whose current sha256 equals the recorded vendored sha256.
security_specific_components = distinct module paths cited in the tables of spec/protections/H23-<variant>.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]
_CITE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_/.\-]*\.py)\b")


def _loc(f: Path) -> int:
    return sum(1 for ln in f.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#"))


def vendored_unchanged(root: Path) -> set[str]:
    vf = root / "VENDORED.json"
    if not vf.is_file():
        return set()
    out = set()
    for rel, ent in json.loads(vf.read_text()).get("files", {}).items():
        f = root / rel
        if f.is_file() and ent.get("vendored_sha256") == hashlib.sha256(f.read_bytes()).hexdigest():
            out.add(rel)
    return out


def security_specific_loc(variant: str, round3: Path = ROUND3) -> dict | None:
    root = round3 / "src" / variant
    if not root.is_dir():
        return None
    skip = vendored_unchanged(root)
    total = excl = 0
    for f in sorted(root.rglob("*.py")):
        n = _loc(f)
        total += n
        if f.relative_to(root).as_posix() not in skip:
            excl += n
    return {"total": total, "excluding_vendored_unchanged": excl}


def security_specific_components(variant: str, round3: Path = ROUND3) -> list[str] | None:
    spec = round3 / "spec" / "protections" / f"H23-{variant}.md"
    root = round3 / "src" / variant
    if not spec.is_file() or not root.is_dir():
        return None
    by_name: dict[str, list[str]] = {}
    for f in root.rglob("*.py"):
        by_name.setdefault(f.name, []).append(f.relative_to(round3).as_posix())
    found: set[str] = set()
    for ln in spec.read_text().splitlines():
        if not ln.startswith("|"):
            continue
        for m in _CITE.findall(ln):
            if (round3 / m).is_file():
                found.add(m)
            elif (root / m).is_file():
                found.add(f"src/{variant}/{m}")
            elif "/" not in m and len(by_name.get(m, [])) == 1:
                found.add(by_name[m][0])
    return sorted(found)
