"""Handwritten-surface measurement: Python code lines (non-blank, non-comment, non-docstring) and declarative config lines.

JSON (IR resources, JSON Schema) is counted in ONE normalised form for every variant: ``json.dumps(obj, indent=2)``, one
line per key/array element. ``assign`` walks a manifest in order; a line already taken is never taken again, so classes
are disjoint and the unassigned remainder of each listed file is reported (never silently dropped).
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

from eoo_exp.util import ROOT

SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}


def code_lines(path: Path) -> dict[int, str]:
    src = Path(path).read_text()
    tree = ast.parse(src)
    doc: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                doc.update(range(b.lineno, b.end_lineno + 1))
    lines = src.splitlines()
    out: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in SKIP:
            for ln in range(tok.start[0], tok.end[0] + 1):
                if ln not in doc:
                    out[ln] = lines[ln - 1]
    return out


def _symbol_range(path: Path, dotted: str) -> range:
    tree, parts = ast.parse(Path(path).read_text()), dotted.split(".")
    nodes = tree.body
    for i, p in enumerate(parts):
        hit = None
        for n in nodes:
            names = [n.name] if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else \
                [t.id for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)] if isinstance(n, (ast.Assign, ast.AnnAssign)) else []
            if p in names:
                hit = n
                break
        if hit is None:
            raise KeyError(f"{path}: no symbol {dotted!r}")
        nodes = getattr(hit, "body", []) if i < len(parts) - 1 else nodes
    start = min([hit.lineno] + [d.lineno for d in getattr(hit, "decorator_list", [])])
    return range(start, hit.end_lineno + 1)


def json_lines(obj) -> int:
    return len(json.dumps(obj, indent=2).splitlines())


def assign(manifest: list[dict]) -> dict:
    """manifest entries (in priority order):
    {"cls", "py": file, "sym": dotted | "re": regex | "all": True}        Python lines
    {"cls", "ir": file, "kind": section, "ids": [..] | "all": True}       IR resources (config lines)
    {"cls", "json": file}                                                  whole JSON file (config lines)
    """
    taken: dict[tuple, str] = {}
    py: dict[str, dict[str, int]] = {}
    cfg: dict[str, dict[str, int]] = {}
    res: dict[str, int] = {}  # declarative resources (IR resources / schema files) per class: verbosity-independent sensitivity
    seen_files: dict[str, dict] = {}
    for m in manifest:
        cls = m["cls"]
        if "py" in m:
            f = ROOT / m["py"]
            cl = seen_files.setdefault(m["py"], code_lines(f))
            if "sym" in m:
                want = set(_symbol_range(f, m["sym"]))
            elif "re" in m:
                want = {ln for ln, t in cl.items() if re.search(m["re"], t)}
            else:
                want = set(cl)
            for ln in sorted(want & set(cl)):
                if (m["py"], ln) not in taken:
                    taken[(m["py"], ln)] = cls
                    py.setdefault(cls, {}).setdefault(m["py"], 0)
                    py[cls][m["py"]] += 1
        elif "ir" in m:
            data = json.loads((ROOT / m["ir"]).read_text())
            items = data[m["kind"]]
            ids = [x["id"] for x in items] if m.get("all") else m["ids"]
            by_id = {x["id"]: x for x in items}
            n = 0
            for i in ids:
                key = (m["ir"], m["kind"], i)
                if key in taken:
                    continue
                taken[key] = cls
                n += json_lines(by_id[i])
                res[cls] = res.get(cls, 0) + 1
            cfg.setdefault(cls, {}).setdefault(f"{m['ir']}:{m['kind']}", 0)
            cfg[cls][f"{m['ir']}:{m['kind']}"] += n
        else:
            key = (m["json"], "*", "*")
            if key not in taken:
                taken[key] = cls
                res[cls] = res.get(cls, 0) + 1
                cfg.setdefault(cls, {})[m["json"]] = json_lines(json.loads((ROOT / m["json"]).read_text()))
    unassigned = {f: sorted(set(cl) - {k[1] for k in taken if len(k) == 2 and k[0] == f}) for f, cl in seen_files.items()}
    return {"python": py, "config": cfg, "resources": res, "python_unassigned": {f: len(v) for f, v in unassigned.items() if v}}


def class_totals(res: dict, cls: str) -> dict:
    p, c = sum(res["python"].get(cls, {}).values()), sum(res["config"].get(cls, {}).values())
    return {"python_loc": p, "config_lines": c, "total": p + c}


def raw_config_lines(files: list[str]) -> int:
    return sum(len((ROOT / f).read_text().splitlines()) for f in files)
