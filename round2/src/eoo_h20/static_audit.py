"""engine-static-audit payload: forbidden-token scan + identity-in-branch scan over every file in the import closure."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from eoo_h16 import audit as A
from eoo_exp.util import ROOT, sha_file

from . import closure as C

IDENT_NAMES = {"package_id", "domain_id", "package_version"}


def identity_branches(sources: dict) -> list[dict]:
    """Branch conditions (if / while / ternary / assert / comprehension filter / any comparison) that read a package or
    domain identity: the structural twin of the token scan (catches ``if eng.model.package_id[:3] == prefix``)."""
    hits = []
    for path, text in sorted(sources.items()):
        tree = ast.parse(text, path)
        tests = []
        for n in ast.walk(tree):
            if isinstance(n, (ast.If, ast.While, ast.IfExp, ast.Assert)):
                tests.append(n.test)
            elif isinstance(n, ast.comprehension):
                tests += n.ifs
            elif isinstance(n, (ast.Compare, ast.Match)):
                tests.append(n if isinstance(n, ast.Compare) else n.subject)
        seen = set()
        for t in tests:
            for m in ast.walk(t):
                name = m.id if isinstance(m, ast.Name) else (m.attr if isinstance(m, ast.Attribute) else (
                    m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else None))
                if name in IDENT_NAMES and (path, m.lineno, name) not in seen:
                    seen.add((path, m.lineno, name))
                    hits.append({"file": path, "line": m.lineno, "name": name})
    return hits


def sources_of(files: list[str], base: Path = ROOT) -> dict:
    return {f: (base / f).read_text() for f in files}


def audit(base: Path = ROOT, src: Path | None = None) -> dict:
    """Audit the closure of the tree rooted at ``base`` (the real round2 by default; a temp copy for mutants)."""
    src = src or base / "src"
    cl = C.closure(src, base)
    srcs = sources_of(cl["files"], base)
    tokens, exempt = A.collect_tokens(), A.exempt_words()
    scan = A.scan_sources(srcs, tokens, exempt)
    ident = identity_branches(srcs)
    per_file = {f: sha_file(base / f) for f in cl["files"]}
    return {"closure": {k: cl[k] for k in ("roots", "files", "external_modules", "third_party", "dynamic_import_sites",
                                          "domain_files_in_closure")},
            "files_scanned": scan["files_scanned"], "string_constants_scanned": scan["string_constants_scanned"],
            "token_count": len(tokens), "exempt_words_present_in_tokens": sorted(set(tokens) & exempt),
            "token_hits": scan["hits"], "token_branch_hits": scan["branch_hits"], "token_literal_hits": scan["literal_hits"],
            "docstring_mentions": scan["docstring_mentions"], "identity_branch_hits": ident,
            "forbidden_core_branches": scan["branch_hits"] + len(ident), "forbidden_core_literals": scan["literal_hits"],
            "file_sha256": per_file}
