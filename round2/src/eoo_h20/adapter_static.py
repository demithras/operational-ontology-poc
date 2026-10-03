"""Static adapter-responsibility audit against the frozen ENGINE_PREREG H20 allowlist / forbidden list.

Per adapter file, from the AST: (1) imports of Engine governance modules, (2) governance vocabulary in a DECISION position
(an if / while / ternary / assert / comparison / comprehension filter), (3) lifecycle state names as string constants,
(4) definitions named after a governance concern, (5) provenance composition (Engine v1.2): an envelope label or any
``EOO-`` trailer key as a string constant, a read of the structured ``envelope`` fields, or the ``envelope_text`` used in
anything but a verbatim pass-through (concatenation, f-string, a method call on it). Data-position uses of governance words
(a docstring, a value) are listed as ``disclosed``, never counted. Vocabulary is the forbidden list of the preregistration.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from eoo_exp.util import ROOT, sha_file

STEMS = {"authority": r"authori[tsz]", "policy": r"polic(y|ies)", "precondition": r"precondition",
         "idempotency": r"idempot", "provenance": r"provenance", "lifecycle": r"lifecycle", "approval": r"approv",
         "principal": r"principal", "capability": r"capabilit", "role": r"^roles?$"}
STATE_NAMES = {"PROPOSED", "PENDING_APPROVAL", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED", "RECONCILED_SUCCESS",
               "RECONCILED_FAILED", "OUTCOME_UNKNOWN", "DENIED"}
FORBIDDEN_ENGINE_MODULES = {"authority", "pipeline", "gates", "outcome", "gatepass", "journal", "capabilities", "snapshot",
                            "engine", "provenance"}
TRAILER_KEY = re.compile(r"^EOO-[A-Za-z0-9-]*")  # every provenance label the Engine renders starts with EOO-
FORBIDDEN_ENGINE_NAMES = {"Engine", "Principal", "Journal", "WriteGrant", "AdapterRegistry", "AppendOnlyLog"}


def adapter_files(root: Path = ROOT) -> list[str]:
    files = sorted(p.relative_to(root).as_posix() for p in (root / "domains").glob("*/adapters/*.py") if p.name != "__init__.py")
    return files + sorted(p.relative_to(root).as_posix() for p in (root / "src/eoo_engine_git").glob("*.py"))


def _doc_ids(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            out.add(id(n.body[0].value))
    return out


def _concern(text: str) -> str | None:
    low = text.lower()
    for name, rx in STEMS.items():
        if re.search(rx, low):
            return name
    return None


# Engine v1.2 (protocol/AUTHOR_DECISIONS_2026-10-03.md decision 2): the Engine composes the provenance envelope and
# adapters write it verbatim, so there is nothing to declare. The v1.1 exception (GitStore._msg) is gone with the code.
DECLARED_EXCEPTIONS: list = []
ENVELOPE_TEXT, ENVELOPE = "envelope_text", "envelope"


def _key_of(n) -> str | None:
    """'k' for x['k'] / x.get('k')."""
    if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
        return n.slice.value
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args \
            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
        return n.args[0].value
    return None


def provenance_composition(tree, docs: set) -> list[dict]:
    """Rule (5): an adapter that composes provenance text itself instead of writing the Engine's envelope verbatim."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and TRAILER_KEY.match(n.value):
            out.append({"line": n.lineno, "kind": "provenance_composition", "how": "provenance label literal",
                        "value": n.value[:40], "concern": "provenance"})
        if _key_of(n) == ENVELOPE:
            out.append({"line": n.lineno, "kind": "provenance_composition", "how": "reads structured envelope fields",
                        "concern": "provenance"})
        uses = []
        if isinstance(n, ast.BinOp):
            uses = [n.left, n.right]
        elif isinstance(n, ast.FormattedValue):
            uses = [n.value]
        elif isinstance(n, ast.Attribute):
            uses = [n.value]
        if any(_key_of(u) == ENVELOPE_TEXT for u in uses):
            out.append({"line": n.lineno, "kind": "provenance_composition", "how": "envelope_text altered, not written verbatim",
                        "concern": "provenance"})
    return out


def _quals(tree) -> dict:
    """line -> qualified name of the innermost enclosing def/class."""
    out: dict = {}

    def visit(n, stack):
        for c in ast.iter_child_nodes(n):
            st = stack + [c.name] if isinstance(c, (ast.FunctionDef, ast.ClassDef)) else stack
            if hasattr(c, "lineno"):
                out.setdefault(c.lineno, ".".join(st))
            visit(c, st)
    visit(tree, [])
    return out


def audit_file(path: str, text: str) -> dict:
    tree = ast.parse(text, path)
    docs = _doc_ids(tree)
    violations, disclosed = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").startswith("eoo_engine") and not (n.module or "").startswith("eoo_engine_git"):
            mod = (n.module or "").split(".")
            names = [a.name for a in n.names]
            bad_mod = len(mod) > 1 and mod[1] in FORBIDDEN_ENGINE_MODULES
            bad_names = [x for x in names if x in FORBIDDEN_ENGINE_NAMES]
            row = {"line": n.lineno, "from": n.module, "names": names}
            (violations if bad_mod or bad_names else disclosed).append(
                {**row, "kind": "engine_governance_import" if bad_mod or bad_names else "engine_function_reused"})
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and (c := _concern(n.name)):
            violations.append({"line": n.lineno, "kind": "governance_definition", "name": n.name, "concern": c})
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and n.value in STATE_NAMES:
            violations.append({"line": n.lineno, "kind": "lifecycle_state_literal", "value": n.value})
    violations += provenance_composition(tree, docs)
    tests = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            tests.append(n.test)
        elif isinstance(n, ast.comprehension):
            tests += n.ifs
        elif isinstance(n, ast.Compare):
            tests.append(n)
    in_test = set()
    for t in tests:
        for m in ast.walk(t):
            name = m.id if isinstance(m, ast.Name) else (m.attr if isinstance(m, ast.Attribute) else (
                m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else None))
            if name and (c := _concern(name)) and (m.lineno, name) not in in_test:
                in_test.add((m.lineno, name))
                violations.append({"line": m.lineno, "kind": "governance_term_in_decision", "term": name, "concern": c})
    for n in ast.walk(tree):  # data-position uses, disclosed
        name = n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs else None
        if name and (c := _concern(name)) and (n.lineno, name) not in in_test and len(name) < 60:
            disclosed.append({"line": n.lineno, "kind": "governance_term_as_data", "value": name, "concern": c})
    q = _quals(tree)
    for v in violations:
        v["qual"] = q.get(v["line"], "")
    declared = [v for v in violations if any(e["file"] == path and e["qual"] == v["qual"] and e["concern"] == v.get("concern")
                                             for e in DECLARED_EXCEPTIONS)]
    return {"file": path, "sha256": None, "violations": [v for v in violations if v not in declared], "declared": declared,
            "disclosed": disclosed}


def audit(files: list[str] | None = None, overrides: dict | None = None, root: Path = ROOT) -> dict:
    """``overrides`` = {relative path: mutated source} (mutation proof); the file list is the real adapter set."""
    files = files if files is not None else adapter_files(root)
    rows = []
    for f in files:
        text = (overrides or {}).get(f)
        r = audit_file(f, text if text is not None else (root / f).read_text())
        r["sha256"] = sha_file(root / f) if f not in (overrides or {}) else "mutated"
        rows.append(r)
    pre = json.loads((root / "protocol/ENGINE_PREREG.json").read_text())["H20"]
    return {"allowed": pre["adapter_allowed"], "forbidden": pre["adapter_forbidden"], "files": rows,
            "declared_exceptions": DECLARED_EXCEPTIONS, "violations": sum(len(r["violations"]) for r in rows),
            "declared_hits": sum(len(r["declared"]) for r in rows), "disclosed": sum(len(r["disclosed"]) for r in rows)}
