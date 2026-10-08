"""Domain-branch audit (R25-6; ORACLE-AND-HARNESS-G3 A5): behaviour first (consistent-renaming metamorphic test), then the
static AST scan, then the self-test that proves the audit non-vacuous on the domain_privilege_branch mutant build."""
from __future__ import annotations

import ast
import copy
import json
import random
import re
from pathlib import Path

from . import replay as RP
from .gen_case import Case
from .rename import Renamer

ROUND3 = Path(__file__).resolve().parents[3]
RESOLUTIONS = ROUND3 / "spec" / "gate3" / "DOMAIN-AUDIT-RESOLUTIONS.json"
AUTH_WORDS = re.compile(r"grant|principal|token|approval|governance|disclosure", re.I)


# -- (a) metamorphic renaming ---------------------------------------------------------------------------------
def rename_case(variant, seed: int, i: int, domain=None, model=None, keep_roles=()) -> dict:
    """Run case (seed, i), replay its inputs on the consistently renamed instance, compare canonical outcomes."""
    g = Case(variant, seed, i, model=model, domain=domain, tag="ren")
    try:
        g.script()
        calls = [{k: c.get(k) for k in ("kind", "rid", "actor", "token_ok", "action", "op", "args", "obo", "doc", "spec", "to",
                                        "crash", "replay", "approved")} for c in g.env.calls]
        outs_a = [{"kind": c["kind"], "status": c["status"], "reason": c["reason"], "body": c.get("body")}
                  for c in g.env.calls if c["kind"] != "advance"]
        marks_a, world_a = RP.marks(g.env), RP.world(g.env)
        inst = g.inst
        auth0, gov0 = copy.deepcopy(inst["auth"]), copy.deepcopy(inst["doc"])
    finally:
        g.env.close()
    rn = Renamer(auth0, gov0, calls, random.Random(f"h25-rename-{seed}-{i}"), keep_roles)
    env2, outs_b = RP.replay(variant, g.domain, g.ops, rn.auth(auth0), rn.fwd(gov0), calls, f"ren2-{seed}-{i}", rn.call)
    try:
        marks_b, world_b = [rn.canon_out(m) for m in RP.marks(env2)], RP.world(env2)
    finally:
        env2.close()
    outs_b = [rn.canon_out(o) for o in outs_b]
    diffs = []
    for n, (a, b) in enumerate(zip(outs_a, outs_b)):
        a = RP_sort(a)
        nr = lambda o: o["reason"].split(":")[0] if o["status"] == "RAISED" and o["reason"] else o["reason"]  # noqa: E731
        if (a["status"], nr(a)) != (b["status"], nr(b)) or RP.canon(a["body"]) != RP.canon(b["body"]):
            diffs.append({"call": n, "kind": a["kind"], "original": [a["status"], a["reason"]],
                          "renamed": [b["status"], b["reason"]]})
    if len(outs_a) != len(outs_b):
        diffs.append({"call": None, "kind": "count", "original": len(outs_a), "renamed": len(outs_b)})
    strip = lambda ms: [{k: v for k, v in m.items() if k not in ("args_digest", "version")} for m in ms]  # noqa: E731
    if RP.canon(strip(RP_sort(marks_a))) != RP.canon(strip(marks_b)):
        diffs.append({"call": None, "kind": "marks", "original": len(marks_a), "renamed": len(marks_b)})
    if RP.canon(world_a) != RP.canon(world_b):
        diffs.append({"call": None, "kind": "world", "original": "differs", "renamed": "differs"})
    return {"case": f"{seed}-{i}", "domain": g.domain, "model": g.model, "calls": len(outs_a), "diffs": diffs[:5],
            "domain_branch": bool(diffs)}


def RP_sort(x):
    from .rename import _sort_bodies
    return _sort_bodies(x)


def rename_audit(variant, seed: int, n: int, domain=None, keep_roles=()) -> dict:
    rows = [rename_case(variant, seed, i, domain=domain, keep_roles=keep_roles) for i in range(n)]
    return {"cases": n, "domain_branch": sum(r["domain_branch"] for r in rows),
            "first": next((r for r in rows if r["domain_branch"]), None),
            "by_domain": {d: sum(1 for r in rows if r["domain"] == d) for d in ("manufacturing", "project")}}


# -- (c) static scan ----------------------------------------------------------------------------------------------
def vocab() -> set[str]:
    from r3_shared.governance import MODELS
    from .gen_model import DOMAINS, fixture, specs
    v = set(DOMAINS) | set(MODELS)
    for m in MODELS:
        for d in DOMAINS:
            doc = fixture(m, d)
            v |= {b["id"] for b in doc["bodies"]} | {x["id"] for x in doc["matters"]}
    for d in DOMAINS:
        _, auth = specs(d)
        v |= {p["id"] for p in auth["principals"]}
        v |= {r for p in auth["principals"] for r in p["roles"]}
        v |= {r["relation"] for p in auth["principals"] for r in p["relations"]}
    return {x for x in v if len(x) > 2}


def _strs(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def _mutant_names(node) -> set[str]:
    """Mutant names switched on inside `node`: `"<name>" in self.mutants` / `self.mutant("<name>")` (G3-E24 s2)."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str) \
                and any(isinstance(o, ast.In) for o in n.ops) \
                and any(isinstance(c, ast.Attribute) and c.attr == "mutants" for c in n.comparators):
            out.add(n.left.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "mutant" \
                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            out.add(n.args[0].value)
    return out


def _live_nodes(tree, active: set[str]):
    """Yield every AST node except code guarded by a mutant switch whose mutant is not active in this build."""
    stack = [tree]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.If) and (_mutant_names(n.test) - active):
            stack.extend(n.orelse)  # the guarded test + body belong to the mutant build only
            continue
        if isinstance(n, (ast.Return, ast.Assign, ast.Expr)) and (_mutant_names(n) - active):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _norm(line: str) -> str:
    return " ".join(line.split())


def scan_source(path: str, text: str, voc: set[str], domain_module: bool, active_mutants=()) -> list[dict]:
    hits = []
    lines = text.splitlines()
    tree = ast.parse(text)
    for n in _live_nodes(tree, set(active_mutants)):
        line = getattr(n, "lineno", 0)
        found = []
        if not domain_module:
            if isinstance(n, ast.Compare):
                found = [("compare", s) for s in _strs(n) if s in voc]
            elif isinstance(n, ast.Dict):
                found = [("dict-dispatch", k.value) for k in n.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value in voc]
            elif hasattr(ast, "MatchValue") and isinstance(n, ast.MatchValue):
                found = [("match", s) for s in _strs(n) if s in voc]
        else:
            names = []
            if isinstance(n, ast.Name):
                names = [n.id]
            elif isinstance(n, ast.Attribute):
                names = [n.attr]
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [getattr(n, "module", "") or ""] + [a.name for a in n.names]
            found = [("authority-vocabulary", nm) for nm in names if AUTH_WORDS.search(nm)]
        for kind, lit in found:
            src = _norm(lines[line - 1]) if 0 < line <= len(lines) else ""
            hits.append({"file": path, "line": line, "kind": kind, "literal": lit, "text": src})
    return hits


def hit_key(variant: str, hit: dict) -> tuple[str, str, str]:
    return (variant, hit["file"], _norm(hit.get("text", "")))


def load_resolutions(path: Path | None = None) -> dict:
    """{(variant, file, normalised text): reason} from the frozen auditor review; a missing file means no resolutions."""
    p = Path(path) if path else RESOLUTIONS
    if not p.is_file():
        return {}
    return {(r["variant"], r["file"], _norm(r["text"])): r.get("reason", "") for r in json.loads(p.read_text()).get("resolutions", [])}


def _declared_in(f: Path) -> list[str]:
    if f.is_file():
        for n in ast.parse(f.read_text()).body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DOMAIN_LOGIC_MODULES" for t in n.targets):
                try:
                    return list(ast.literal_eval(n.value))
                except Exception:  # noqa: BLE001
                    return []
    return []


def declared_domain_modules(pkg_dir: Path) -> list[str]:
    """DOMAIN_LOGIC_MODULES from the variant's declaration: variant.py, else the package __init__.py (G3-E24 s3)."""
    return _declared_in(pkg_dir / "variant.py") or _declared_in(pkg_dir / "__init__.py")


def _is_domain_module(rel_pkg: str, rel_root: str, modules) -> bool:
    for m in modules:
        m = m.strip("/")
        if rel_root == m or rel_root.startswith(m + "/") or rel_pkg == m or rel_pkg.startswith(m + "/") \
                or ("/" not in m and rel_pkg.endswith(m)):
            return True
    return False


def static_scan(pkg_dir: Path | None = None, sources: dict[str, str] | None = None, domain_modules=(),
                variant: str | None = None, active_mutants=(), resolutions=None) -> dict:
    voc = vocab()
    files, roots = {}, {}
    if pkg_dir is not None:
        pkg_dir = Path(pkg_dir)
        try:
            base = pkg_dir.resolve().relative_to(ROUND3.resolve())
        except ValueError:
            base = Path(pkg_dir.name)
        for p in sorted(pkg_dir.rglob("*.py")):
            rel = str(p.relative_to(pkg_dir))
            roots[rel] = str(base / rel)
            files[rel] = p.read_text()
        domain_modules = tuple(domain_modules) or tuple(declared_domain_modules(pkg_dir))
        variant = variant or pkg_dir.name
    files.update(sources or {})
    res = load_resolutions() if resolutions is None else resolutions
    hits, resolved = [], []
    for name, text in files.items():
        rr = roots.get(name, name)
        for h in scan_source(rr, text, voc, _is_domain_module(name, rr, domain_modules), active_mutants):
            reason = res.get(hit_key(variant or "", h))
            (resolved.append({**h, "reason": reason}) if reason is not None else hits.append(h))
    return {"files": len(files), "domain_logic_modules": list(domain_modules), "hits": hits, "hit_count": len(hits),
            "resolved": resolved, "resolved_count": len(resolved), "active_mutants": sorted(active_mutants)}
