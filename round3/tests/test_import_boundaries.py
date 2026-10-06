"""AST import scan enforcing the package edges (common.md). Never weaken."""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PKGS = ("r3_shared", "r3_oracle", "r3_harness", "paladin", "conventional")
ALLOWED = {
    "r3_shared": set(),
    "r3_oracle": {"r3_shared"},
    "r3_harness": {"r3_shared", "r3_oracle"},
    "paladin": {"r3_shared"},
    "conventional": {"r3_shared"},
}
# Variant packages (and shared/oracle) may never import round2 engine/toolchain/hdd packages unless allowed here.
ROUND2 = ("eoo_",)
ROUND2_ALLOWED = {"paladin": ("eoo_",)}  # Paladin builds on the Round 2 Engine/Toolchain
ROUND2_EXTRA_BANNED = {"conventional": ("eoo_",), "r3_oracle": ("eoo_",), "r3_shared": ("eoo_",),
                       "r3_harness": ("eoo_",)}


def imported_roots(source: str) -> set[tuple[str, int]]:
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out |= {(a.name.split(".")[0], node.lineno) for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add((node.module.split(".")[0], node.lineno))
            # `from . import x` style is relative (level>0) and stays within the package.
    return out


def violations(pkg: str, source: str, fname: str = "<src>") -> list[str]:
    bad = []
    for root, line in imported_roots(source):
        if root in PKGS and root != pkg and root not in ALLOWED[pkg]:
            bad.append(f"{fname}:{line}: {pkg} must not import {root}")
        if any(root.startswith(p) for p in ROUND2_EXTRA_BANNED.get(pkg, ())):
            bad.append(f"{fname}:{line}: {pkg} must not import round2 package {root}")
    return bad


def scan_tree(src: Path = SRC) -> list[str]:
    out = []
    for pkg in PKGS:
        for f in sorted((src / pkg).rglob("*.py")):
            out += violations(pkg, f.read_text(), str(f.relative_to(src)))
    return out


def test_repo_respects_boundaries():
    assert scan_tree() == []


def test_checker_catches_known_negatives(tmp_path):
    # known negative: forbidden edges must be flagged (the checker is not vacuous)
    assert violations("conventional", "import paladin.engine")
    assert violations("paladin", "from conventional import x")
    assert violations("r3_oracle", "from paladin.variant import PaladinVariant")
    assert violations("r3_oracle", "import conventional")
    assert violations("r3_shared", "from r3_harness import run")
    assert violations("r3_harness", "from paladin import variant")
    assert violations("conventional", "from eoo_engine import Engine")
    assert violations("r3_oracle", "import eoo_engine.authority")
    # known positives: allowed edges pass
    assert not violations("r3_harness", "from r3_shared import world\nfrom r3_oracle import meter")
    assert not violations("paladin", "from r3_shared import world\nfrom eoo_engine import Engine")
    assert not violations("conventional", "from r3_shared.world import WorldHandle\nimport json")
    # tree-level: a planted file is caught by scan_tree
    pkg = tmp_path / "r3_oracle"
    pkg.mkdir()
    for p in PKGS:
        (tmp_path / p).mkdir(exist_ok=True)
    (pkg / "bad.py").write_text("from paladin import x\n")
    assert scan_tree(tmp_path) == ["r3_oracle/bad.py:1: r3_oracle must not import paladin"]
