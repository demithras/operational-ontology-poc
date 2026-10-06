"""Static facts about the Toolchain: its import closure (never the oracle / Engine / domain logic) and domain-token scan."""
from __future__ import annotations

import ast
import re

from eoo_exp.util import ROOT, sha_file

FORBIDDEN = ("oracles", "eoo_engine", "eoo_engine_git", "domains", "eoo_h21", "eoo_h20", "eoo_h18", "eoo_h17", "eoo_exp")


def imports_of(src: str) -> list:
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split(".")[0])
    return sorted(out)


def _oracle_in_call_args(src: str) -> bool:
    """A string constant mentioning the oracle passed to any call (importlib / path joins), i.e. a dynamic import of it."""
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            for a in list(n.args) + [k.value for k in n.keywords]:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and "oracle" in a.value.lower():
                    return True
    return False


def toolchain_facts(base=None) -> dict:
    files = sorted((base or ROOT / "src/eoo_toolchain").glob("*.py"))
    rows = [{"file": p.name if base else p.relative_to(ROOT).as_posix(), "sha256": sha_file(p), "imports": imports_of(p.read_text()),
             "forbidden_imports": [i for i in imports_of(p.read_text()) if i in FORBIDDEN], "lines": len(p.read_text().splitlines())} for p in files]
    # generated modules import eoo_toolchain only; dynamic imports (importlib) are listed so a reader can overrule them
    dyn = sorted(p.name for p in files if re.search(r"importlib|__import__", p.read_text()))
    return {"files": rows, "forbidden_imports": sorted({i for r in rows for i in r["forbidden_imports"]}),
            "imports_oracle": any("oracles" in r["imports"] for r in rows) or any(_oracle_in_call_args(p.read_text()) for p in files),
            "files_with_dynamic_import_machinery": dyn, "total_lines": sum(r["lines"] for r in rows)}


def oracle_facts() -> list:
    out = []
    for p in sorted((ROOT / "oracles/h21").glob("*.py")):
        imps = imports_of(p.read_text())
        out.append({"file": p.relative_to(ROOT).as_posix(), "sha256": sha_file(p), "imports": imps,
                    "forbidden_imports": [i for i in imps if i in ("eoo_engine", "eoo_engine_git", "eoo_toolchain", "domains", "eoo_h21", "hdd", "eoo_ir")]})
    return out


def domain_token_scan(irs: list, base=None) -> dict:
    """Quoted domain identifiers (resource ids) appearing as string constants in the Toolchain source."""
    ids = set()
    for ir in irs:
        for k in ("object_types", "link_types", "interfaces", "functions", "actions", "authority_rules"):
            ids |= {r["id"] for r in ir[k]}
        ids |= {ir["package_id"]}
    generic = {"Obj", "any", "type", "role", "principal", "relation"}
    ids -= generic
    hits = {}
    for p in sorted((base or ROOT / "src/eoo_toolchain").glob("*.py")):
        consts = {n.value for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        h = sorted(c for c in consts if c in ids)
        if h:
            hits[p.name] = h
    known_neg = sorted(c for c in {"transfer_inventory", "Hypothesis"} if c in ids)
    return {"identifiers_checked": len(ids), "hits": hits, "known_negative_ids_are_in_the_checked_set": known_neg}
