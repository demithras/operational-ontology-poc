"""Import-graph closure of the Engine-participating code: which files must the static audit scan?

Roots = every ``.py`` under ``src/eoo_engine*`` (the Engine and its Git-backed store). A file is added when a scanned file
imports it (``import a.b``, ``from a import b`` where ``b`` may be a submodule, relative imports) and it resolves to a
file under ``src/`` or ``domains/``. Stdlib / third-party imports are listed, not followed. Dynamic import sites
(importlib, __import__, exec, eval, runpy, compile) are listed: a static closure cannot see through them.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from eoo_exp.util import ROOT

SRC = ROOT / "src"
DYNAMIC = {"importlib", "__import__", "exec", "eval", "runpy", "compile", "import_module"}


def _roots(src: Path) -> list[Path]:
    return sorted(p for d in src.glob("eoo_engine*") if d.is_dir() for p in d.rglob("*.py"))


def _resolve(mod: str, base: Path, root: Path) -> Path | None:
    """File of dotted module ``mod`` relative to the search roots (``src`` and the repo root of round2)."""
    parts = mod.split(".")

    def exact(p: Path) -> bool:  # case-exact existence (macOS is case-insensitive: ``Engine`` must not resolve to engine.py)
        return p.is_file() and p.name in os.listdir(p.parent)

    for top in (base, root):
        pkg = top.joinpath(*parts)
        if pkg.is_dir() and pkg.name in os.listdir(pkg.parent) and exact(pkg / "__init__.py"):
            return pkg / "__init__.py"
        if exact(pkg.with_suffix(".py")):
            return pkg.with_suffix(".py")
    return None


def imports_of(path: Path, src: Path, root: Path) -> tuple[set, set]:
    """(resolved local files, unresolved top-level module names) imported by ``path``."""
    tree = ast.parse(path.read_text(), str(path))
    pkg_parts = list(path.relative_to(src).parent.parts) if path.is_relative_to(src) else list(path.relative_to(root).parent.parts)
    local, other = set(), set()

    def add(mod: str):
        f = _resolve(mod, src, root)
        (local.add(f) if f else other.add(mod.split(".")[0]))
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                add(a.name)
                parts = a.name.split(".")
                for k in range(1, len(parts)):  # importing a.b.c executes a/__init__ and a/b/__init__ too
                    add(".".join(parts[:k]))
        elif isinstance(n, ast.ImportFrom):
            base = ".".join(pkg_parts[: len(pkg_parts) - (n.level - 1)]) if n.level else ""
            mod = ".".join(x for x in (base, n.module or "") if x)
            if mod:
                add(mod)
            for a in n.names:  # ``from pkg import name``: name may be a submodule (else it is an attribute: ignore)
                f = _resolve(f"{mod}.{a.name}" if mod else a.name, src, root)
                if f:
                    local.add(f)
                elif not mod:
                    other.add(a.name.split(".")[0])
    return local, other


def dynamic_sites(path: Path) -> list[dict]:
    out = []
    for n in ast.walk(ast.parse(path.read_text(), str(path))):
        name = n.id if isinstance(n, ast.Name) else (n.attr if isinstance(n, ast.Attribute) and n.attr == "import_module" else None)
        if name in DYNAMIC and isinstance(getattr(n, "ctx", None), ast.Load):
            out.append({"line": n.lineno, "name": name})
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] in ("importlib", "runpy") for a in n.names):
            out.append({"line": n.lineno, "name": "import " + ",".join(a.name for a in n.names)})
    return out


def domain_roots(root: Path = ROOT) -> list[Path]:
    return sorted(p for p in (root / "domains").rglob("*.py") if "__pycache__" not in p.parts)


def closure(src: Path = SRC, root: Path = ROOT, roots: list[Path] | None = None) -> dict:
    todo, seen, external, edges = list(roots if roots is not None else _roots(src)), set(), set(), {}
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        local, other = imports_of(f, src, root)
        external |= other
        edges[f.relative_to(root).as_posix()] = sorted(x.relative_to(root).as_posix() for x in local)
        todo += [x for x in local if x not in seen]
    files = sorted(p.relative_to(root).as_posix() for p in seen)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    return {"roots": [p.relative_to(root).as_posix() for p in (roots if roots is not None else _roots(src))], "files": files, "edges": edges,
            "external_modules": sorted(external), "third_party": sorted(m for m in external if m not in stdlib),
            "dynamic_import_sites": {f: s for f in files if (s := dynamic_sites(root / f))},
            "domain_files_in_closure": [f for f in files if f.startswith("domains/")]}
