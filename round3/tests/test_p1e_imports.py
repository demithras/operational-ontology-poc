"""P1e import obligations: variants may not import oracle-side helpers (r3_oracle.*, already in test_import_boundaries)
nor the HARNESS-ONLY seeding API (WorldStore / .seed) from r3_shared.world; shared Gate 3 forms contain no visibility logic."""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
HARNESS_ONLY_NAMES = {"WorldStore", "WorldReader"}


def violations(source: str, fname="<src>"):
    bad = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").startswith("r3_oracle"):
            bad.append(f"{fname}:{n.lineno}: oracle import")
        if isinstance(n, ast.Import):
            bad += [f"{fname}:{n.lineno}: oracle import" for a in n.names if a.name.startswith("r3_oracle")]
        if isinstance(n, ast.ImportFrom) and not n.level and n.module == "r3_shared.world":
            bad += [f"{fname}:{n.lineno}: harness-only {a.name}" for a in n.names if a.name in HARNESS_ONLY_NAMES]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "seed" and n.args \
                and isinstance(n.args[0], (ast.List, ast.ListComp)) and any(k.arg == "writer" for k in n.keywords):
            bad.append(f"{fname}:{n.lineno}: WorldStore.seed call")
    return bad


@pytest.mark.parametrize("pkg", ["paladin", "conventional"])
def test_variant_sources_use_no_harness_only_helpers(pkg):
    bad = []
    for f in (SRC / pkg).rglob("*.py"):
        bad += violations(f.read_text(), str(f))
    assert bad == []


def test_scanner_known_negatives_fire():
    assert violations("from r3_oracle.constitution import X")
    assert violations("import r3_oracle.disclosure")
    assert violations("from r3_shared.world import WorldStore")
    assert violations("store.seed([[]], writer='harness-seed')")
    assert violations("from r3_shared.world import WorldHandle") == []
    assert violations("rng.seed(5)") == []


def test_shared_forms_have_no_visibility_logic():
    for name in ("disclosure.py", "constitutional.py", "governance.py"):
        t = (SRC / "r3_shared" / name).read_text()
        assert "low_view" not in t.split('"""', 2)[2] and "def visible" not in t
        assert "import r3_oracle" not in t and "from r3_oracle" not in t
