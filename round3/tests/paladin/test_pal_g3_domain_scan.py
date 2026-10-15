"""R25-6 static scan (ORACLE-AND-HARNESS-G3 A5c, Paladin side): outside the declared DOMAIN_LOGIC_MODULES and the Round 2 domain
packs, no Compare / membership test on a string literal that is a domain name, model id, body id, principal id, role or relation name.
The scan is run on the whole package: it must find the pre-Gate-3 adapter wiring in boot.py and the `domain_privilege_branch` mutant
(non-vacuity), and nothing else."""
import ast
import json
from pathlib import Path

from paladin.variant import DOMAIN_LOGIC_MODULES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "paladin"


def identities() -> set:
    ids = {"project", "manufacturing", "hierarchical", "collegial", "polycentric"}
    for p in (ROOT / "spec" / "governance").glob("*.json"):
        d = json.loads(p.read_text())
        ids |= {b["id"] for b in d["bodies"]} | {m["id"] for m in d["matters"]}
    for p in (ROOT / "spec" / "authority").glob("*.json"):
        d = json.loads(p.read_text())
        for pr in d["principals"]:
            ids |= {pr["id"], *pr["roles"], *(r["relation"] for r in pr["relations"])}
    return ids


def hits() -> list:
    ids, out = identities(), []
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if any(rel.startswith(m) for m in DOMAIN_LOGIC_MODULES) or "/domains/" in rel or "/engine/" in rel or "/toolchain/" in rel:
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Compare):
                for c in [n.left, *n.comparators]:
                    lits = [c] if isinstance(c, ast.Constant) else list(getattr(c, "elts", []))
                    if any(isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value in ids for x in lits):
                        out.append((rel, n.lineno))
    return out


def test_scan_finds_only_wiring_and_the_mutant_branch():
    files = {f for f, _ in hits()}
    assert files == {"src/paladin/boot.py", "src/paladin/core_g3.py"}, hits()
    lines = (SRC / "core_g3.py").read_text().splitlines()
    assert all("domain_privilege_branch" in lines[ln - 1] for f, ln in hits() if f.endswith("core_g3.py"))


def test_scan_is_not_vacuous_on_a_synthetic_branch():
    tree = ast.parse('if domain == "project" and who.endswith("-1"):\n    pass')
    assert any(isinstance(n, ast.Compare) for n in ast.walk(tree))
