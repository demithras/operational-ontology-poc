"""Static audit (AST): does any code in the scanned scope compare / branch / key on / contain a domain identity?

Domain identity = package id, domain id or any resource id of the registered domain IRs. A string constant (not a
docstring) that equals such a token, or contains it as a whole word, is a HIT; its syntactic position classifies it as
a branch position (compare, membership, dict key, subscript, call argument, match) or a plain literal.
Words the frozen IR schema or the preregistration themselves define are exempt (reported, never silently).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from eoo_exp.util import ROOT

KINDS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
         "observation_types", "constraints")
BRANCH = ("compare", "membership", "dict_key", "subscript", "call_arg", "match")


def domain_files() -> dict:
    return {"manufacturing": ROOT / "domains/manufacturing/ir.json", "project-v1": ROOT / "domains/project/ir.json",
            "project-v2": ROOT / "domains/project/ir.v2.json"}


def collect_tokens(files: dict | None = None) -> dict:
    """token -> sorted origins (e.g. ['manufacturing:object_types', 'domain_id'])."""
    tokens: dict[str, set] = {}
    for name, f in (files or domain_files()).items():
        pkg = json.loads(Path(f).read_text())
        for key in ("package_id", "domain_id"):
            if pkg.get(key):
                tokens.setdefault(pkg[key], set()).add(f"{name}:{key}")
        for kind in KINDS:
            for r in pkg[kind]:
                tokens.setdefault(r["id"], set()).add(f"{name}:{kind}")
    return {t: sorted(o) for t, o in tokens.items()}


def exempt_words() -> set:
    out = set()

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k in ("properties", "$defs") and isinstance(v, dict):
                    out.update(v)
                if k == "enum":
                    out.update(x for x in v if isinstance(x, str))
                if k == "const" and isinstance(v, str):
                    out.add(v)
                if k == "required" and isinstance(v, list):
                    out.update(v)
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(json.loads((ROOT / "ontology/ir.schema.json").read_text()))
    out |= set(json.loads((ROOT / "protocol/ENGINE_PREREG.json").read_text())["H17"]["gate_tokens"])
    return out


def _docstring_ids(tree) -> set:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                ids.add(id(b.value))
    return ids


def _position(node, parents) -> str:
    p = parents.get(id(node))
    if isinstance(p, (ast.Tuple, ast.List, ast.Set)):
        gp = parents.get(id(p))
        return "membership" if isinstance(gp, ast.Compare) else "plain"
    if isinstance(p, ast.Compare):
        return "compare"
    if isinstance(p, ast.Dict) and node in p.keys:
        return "dict_key"
    if isinstance(p, ast.Subscript):
        return "subscript"
    if isinstance(p, ast.Call) and node in p.args:
        return "call_arg"
    if isinstance(p, ast.keyword) or isinstance(p, ast.Call):
        return "call_arg"
    if isinstance(p, (ast.MatchValue, ast.MatchSingleton)):
        return "match"
    return "plain"


def _matcher(tokens: dict):
    exact = set(tokens)
    words = {t: re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(t) + r"(?![A-Za-z0-9_-])") for t in tokens if len(t) >= 4}

    def match(value: str) -> list[str]:
        hits = [t for t in exact if value == t]
        if not hits:
            hits = [t for t, rx in words.items() if rx.search(value)]
        return sorted(hits)
    return match


def scan_sources(sources: dict, tokens: dict, exempt: set) -> dict:
    """sources: {path: source text}. Returns {hits, docstring_mentions, branch_hits, literal_hits, files_scanned}."""
    match = _matcher({t: o for t, o in tokens.items() if t not in exempt})
    hits, doc_mentions = [], []
    for path, text in sorted(sources.items()):
        tree = ast.parse(text, path)
        parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            found = match(node.value)
            if not found:
                continue
            row = {"file": path, "line": node.lineno, "tokens": found, "value": node.value[:80]}
            if id(node) in docs:
                doc_mentions.append(row)
                continue
            row["position"] = _position(node, parents)
            hits.append(row)
    branch = [h for h in hits if h["position"] in BRANCH]
    return {"files_scanned": len(sources), "string_constants_scanned": sum(
        1 for t in sources.values() for n in ast.walk(ast.parse(t)) if isinstance(n, ast.Constant) and isinstance(n.value, str)),
        "branch_hits": len(branch), "literal_hits": len(hits), "hits": hits, "docstring_mentions": doc_mentions}


def read_dir(d: Path, base: Path = ROOT) -> dict:
    return {p.relative_to(base).as_posix(): p.read_text() for p in sorted(Path(d).glob("*.py"))}
