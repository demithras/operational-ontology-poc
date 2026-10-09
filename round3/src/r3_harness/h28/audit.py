"""Adapter-side governance audit (PROT-H28 R28-11/R28-12): behaviour first (twin differential / oracle decision equality / artefact
probes - computed by judge.py), static AST scan second, self-test third. The static scan reads ONLY source text of the variant's
declared ADAPTER_MODULES (P1f-8); it never imports a variant. Hits are resolved only through the frozen
spec/gate4/ADAPTER-AUDIT-RESOLUTIONS.json (G3-E24/E29 rules); an unresolved hit is governance_in_adapter."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]
RESOLUTIONS = ROUND3 / "spec" / "gate4" / "ADAPTER-AUDIT-RESOLUTIONS.json"
IMPORT_WORDS = re.compile(r"authority|policy|approval|governance|disclosure|authz|pdp|constitution|delegation", re.I)
REPLY_WORDS = {"approval", "grant", "on_behalf_of", "policy", "approved", "denied", "principal", "role", "threshold", "decision"}
TRIVIAL = {0, 1, 2, 3, -1}
# frozen P1f vocabulary (reply status, decision status, outcome states): touching these is protocol, not business policy (R28-12 resolvability)
PROTOCOL_VOCAB = {"OK", "FAILED", "TIMEOUT", "DENIED", "INVALID", "UNAVAILABLE", "UNKNOWN", "PENDING", "RECONCILED_SUCCESS",
                  "RECONCILED_FAILED", "DIVERGED", "SUPPORTED", "REJECTED", "INCONCLUSIVE"}


def rule_literals(ops_spec: dict) -> set:
    """Constants of the ops-spec deny/require_approval rule `when` and precondition predicates (R28-12 iii)."""
    out: set = set()

    def walk(n):
        if isinstance(n, dict):
            if "lit" in n:
                v = n["lit"]
                for x in (v if isinstance(v, list) else [v]):
                    if isinstance(x, bool) or x is None:
                        continue
                    if isinstance(x, (int, float)) and x in TRIVIAL:
                        continue
                    if isinstance(x, str) and (len(x) < 3 or x in PROTOCOL_VOCAB):
                        continue
                    out.add(x)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    for op in ops_spec["operations"]:
        for r in op.get("business_rules", []):
            walk(r.get("when"))
        for p in op.get("preconditions", []):
            walk(p.get("predicate"))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _docstring_ids(tree) -> set:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            ids.add(id(n.body[0].value))
    return ids


def _scopes(tree):
    sc = []

    def visit(n, stack):
        for c in ast.iter_child_nodes(n):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sc.append((c.lineno, getattr(c, "end_lineno", c.lineno), ".".join(stack + [c.name])))
                visit(c, stack + [c.name])
            else:
                visit(c, stack)
    visit(tree, [])
    return sc


def _scope_of(sc, line):
    best = "<module>"
    for a, b, q in sc:
        if a <= line <= b and (best == "<module>" or len(q) >= len(best)):
            best = q
    return best


def scan_source(path: str, text: str, literals: set) -> list[dict]:
    tree, lines = ast.parse(text), text.splitlines()
    skip, sc, hits = _docstring_ids(tree), _scopes(tree), []

    def add(node, kind, lit):
        line = getattr(node, "lineno", 0)
        hits.append({"file": path, "line": line, "kind": kind, "literal": lit, "scope": _scope_of(sc, line),
                     "text": _norm(lines[line - 1]) if 0 < line <= len(lines) else ""})
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] + [a.name for a in n.names])
            for nm in names:
                if IMPORT_WORDS.search(nm):
                    add(n, "import-authority-module", nm)
        if isinstance(n, ast.Constant) and id(n) not in skip:
            v = n.value
            if isinstance(v, str) and v in REPLY_WORDS:
                add(n, "reply-or-authority-key", v)
            elif not isinstance(v, bool) and v in literals and isinstance(v, (str, int, float)) and type(v) in {type(x) for x in literals if x == v}:
                add(n, "business-rule-literal", v)
    seen, uniq = set(), []
    for h in sorted(hits, key=lambda h: (h["file"], h["line"], h["kind"], str(h["literal"]))):
        k = (h["file"], h["line"], h["kind"], str(h["literal"]))
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq


def hit_key(variant: str, h: dict) -> tuple:
    return (variant, h["file"], h.get("scope") or "<module>", _norm(h.get("text", "")))


def load_resolutions(path: Path | None = None) -> dict:
    p = Path(path) if path else RESOLUTIONS
    if not p.is_file():
        return {}
    return {(r["variant"], r["file"], r["scope"], _norm(r["text"])): r.get("reason", "")
            for r in json.loads(p.read_text()).get("resolutions", []) if r.get("scope")}


def declared_adapter_modules(pkg_dir: Path) -> list[str] | None:
    """ADAPTER_MODULES from variant.py, else the package __init__.py (P1f-8, G3-E24 s3). None = not declared."""
    for f in (pkg_dir / "variant.py", pkg_dir / "__init__.py"):
        if f.is_file():
            for n in ast.parse(f.read_text()).body:
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ADAPTER_MODULES" for t in n.targets):
                    try:
                        return list(ast.literal_eval(n.value))
                    except Exception:  # noqa: BLE001
                        return []
    return None


def module_file(mod: str, roots=(ROUND3 / "src", ROUND3)) -> Path | None:
    for r in roots:
        base = r.joinpath(*mod.split("."))
        for cand in (base.with_suffix(".py"), base / "__init__.py"):
            if cand.is_file():
                return cand
    return None


def static_scan(variant: str, modules: list[str] | None, literals: set, resolutions: dict | None = None) -> dict:
    if modules is None:
        return {"declared": False, "modules": [], "files": [], "hits": [], "resolved": [], "unresolved_count": 0,
                "note": "ADAPTER_MODULES not declared by the variant (P1f-8)"}
    res = load_resolutions() if resolutions is None else resolutions
    files, hits, resolved, missing = [], [], [], []
    for m in modules:
        f = module_file(m)
        if f is None:
            missing.append(m)
            continue
        rel = str(f.relative_to(ROUND3))
        files.append(rel)
        for h in scan_source(rel, f.read_text(), literals):
            reason = res.get(hit_key(variant, h))
            (resolved.append({**h, "reason": reason}) if reason is not None else hits.append(h))
    return {"declared": True, "modules": modules, "files": files, "missing_modules": missing, "hits": hits, "resolved": resolved,
            "unresolved_count": len(hits) + len(missing), "resolutions_file": str(RESOLUTIONS.relative_to(ROUND3)),
            "resolutions_present": RESOLUTIONS.is_file()}


def all_literals() -> set:
    from . import specs
    out: set = set()
    for d in specs.DOMAINS:
        out |= rule_literals(specs.load(d)[0])
    return out


def build_audit(J: dict, variant: str, modules, selftest: dict | None) -> dict:
    """adapter-governance-audit.json: twin differential (a), oracle decision mismatches (b), artefact probes (c), static scan, self-test."""
    twin, oracle_mm, artefact = [], [], []
    for r in J["rows"]:
        for g in r["gov"]:
            (twin if g["sub"] == "adapter_influenced_decision" else artefact if g["sub"] == "adapter_artefact_consumed" else oracle_mm).append(
                {"case": r["case"], **g})
    probes = [r["case"] for r in J["rows"] if any(p in ("G1", "G2") for p in r["prims"])]
    return {"behavioural": {"twin_differential": twin, "oracle_decision_mismatches": oracle_mm, "artefact_probe_hits": artefact,
                            "artefact_probe_cases": len(probes), "twin_pairs": sum(1 for r in J["rows"] if r["case"].startswith("byz"))},
            "static": static_scan(variant, modules, all_literals()), "self_test": selftest or {"run": False}}
