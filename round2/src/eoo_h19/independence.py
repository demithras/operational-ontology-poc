"""Static proof that the H19 oracle is a pure model: only stdlib data helpers, no Engine / store / domain / harness import, no I/O."""
from __future__ import annotations

import ast

from eoo_exp.util import ROOT

ORACLE_FILES = sorted((ROOT / "oracles/h19").glob("*.py"))
ALLOWED = {"__future__", "copy", "hashlib", "json"}
IO_NAMES = {"open", "subprocess", "os", "pathlib", "socket", "sqlite3", "requests"}


def oracle_imports(files=None) -> dict:
    bad, seen = [], {}
    for f in (files if files is not None else ORACLE_FILES):
        mods, names = set(), set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
            elif isinstance(n, ast.Name):
                names.add(n.id)
        seen[f.name] = sorted(mods)
        bad += [f"{f.name}: import {m}" for m in mods if m not in ALLOWED]
        bad += [f"{f.name}: uses {m}" for m in sorted(names & IO_NAMES)]
    return {"files": seen, "allowed_imports": sorted(ALLOWED), "forbidden": bad, "independent": not bad and bool(seen)}
