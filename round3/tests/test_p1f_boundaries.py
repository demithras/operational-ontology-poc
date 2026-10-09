"""P1f import edges (in addition to tests/test_import_boundaries.py, which stays untouched): variants may import
r3_shared.extadapter/extcap/extobs/extsystems/extsem/outcome but never the ExternalWorld service (extworld_server, extworld_core);
r3_shared itself imports no oracle/harness/variant; the outcome module holds no outcome function."""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
SERVICE = ("r3_shared.extworld_server", "r3_shared.extworld_core")


def service_imports(source: str, fname="<src>") -> list[str]:
    bad = []
    for node in ast.walk(ast.parse(source)):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            mods = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
        for m in mods:
            if any(m == s or m.startswith(s + ".") for s in SERVICE):
                bad.append(f"{fname}:{node.lineno}: {m}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(node.value.startswith(s) for s in SERVICE):
            bad.append(f"{fname}:{node.lineno}: string {node.value!r}")
        if isinstance(node, ast.Name) and node.id == "ExternalWorldCore":
            bad.append(f"{fname}:{node.lineno}: ExternalWorldCore")
    return bad


def test_scanner_catches_known_negatives():
    for src in ("import r3_shared.extworld_server", "from r3_shared import extworld_core", "from r3_shared.extworld_core import X",
                "from r3_shared.extworld_server import main", "import importlib\nimportlib.import_module('r3_shared.extworld_core')",
                "x = ExternalWorldCore"):
        assert service_imports(src), src
    for ok in ("from r3_shared.extcap import attenuate", "from r3_shared.extobs import ObservationClient",
               "from r3_shared.extworld import ExternalClient", "from r3_shared import extadapter"):
        assert service_imports(ok) == [], ok


@pytest.mark.parametrize("pkg", ["paladin", "conventional", "r3_oracle"])
def test_variants_and_oracle_never_import_the_service(pkg):
    hits = []
    for f in sorted((SRC / pkg).rglob("*.py")) if (SRC / pkg).exists() else []:
        hits += service_imports(f.read_text(), str(f.relative_to(SRC)))
    assert hits == []


def test_r3_shared_imports_nothing_above_it():
    forbidden = {"r3_oracle", "r3_harness", "paladin", "conventional"}
    for f in (SRC / "r3_shared").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            assert not [n for n in names if n.split(".")[0] in forbidden], (f.name, names)


def test_outcome_module_has_forms_only():
    tree = ast.parse((SRC / "r3_shared" / "outcome.py").read_text())
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert funcs == {"validate_outcome", "validate_outcomes", "allowed_transition"}
