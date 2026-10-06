"""Import closure, forbidden-token scan, identity-in-branch scan, oracle independence: clean on the real tree, red on planted cases."""
import ast
import shutil

import pytest

from eoo_exp.util import ROOT
from eoo_h20 import closure as C
from eoo_h20 import static_audit as SA


def test_closure_contains_every_engine_file_and_the_ir_validator():
    c = C.closure()
    on_disk = {p.relative_to(ROOT).as_posix() for d in (ROOT / "src").glob("eoo_engine*") for p in d.rglob("*.py") if "__pycache__" not in p.parts}
    assert on_disk <= set(c["files"]) and "src/eoo_ir/validate.py" in c["files"] and len(c["files"]) >= 30
    assert c["dynamic_import_sites"] == {} and c["domain_files_in_closure"] == []


def test_closure_is_case_exact():
    """macOS resolves ``Engine`` to engine.py: the closure must not invent a second spelling."""
    files = C.closure(roots=C.domain_roots())["files"]
    assert "src/eoo_engine/Engine.py" not in files and "src/eoo_engine/engine.py" in files


def test_closure_follows_a_planted_import(tmp_path):
    t = tmp_path / "round2"
    shutil.copytree(ROOT / "src", t / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    (t / "src/eoo_engine/zz_hook.py").write_text("X = 1\n")
    (t / "src/eoo_h20/hook_target.py").write_text("Y = 2\n")
    eng = t / "src/eoo_engine/engine.py"
    eng.write_text(eng.read_text() + "\nfrom eoo_h20 import hook_target\n")
    c = C.closure(t / "src", t)
    assert "src/eoo_h20/hook_target.py" in c["files"] and "src/eoo_engine/zz_hook.py" in c["files"]


def test_closure_reports_a_dynamic_import_site(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import importlib\nm = importlib.import_module('os')\nexec('1')\n")
    assert {s["name"] for s in C.dynamic_sites(f)} >= {"import_module", "exec", "import importlib"}


def test_real_tree_is_clean():
    a = SA.audit()
    assert (a["forbidden_core_branches"], a["forbidden_core_literals"]) == (0, 0)
    assert a["files_scanned"] >= 30 and a["token_count"] > 150 and a["string_constants_scanned"] > 1000


@pytest.mark.parametrize("src,kind", [
    ("def f(eng):\n    if eng.model.package_id == 'manufacturing-ontology':\n        return 1\n", "branch"),
    ("def f(spec):\n    return spec.rid == 'transfer_inventory'\n", "branch"),
    ("def f(spec):\n    X = {'transfer_inventory': 1}\n    return X\n", "branch"),
    ("def f(spec):\n    NAMES = 'transfer_inventory'\n", "literal"),
])
def test_token_scan_known_negatives(src, kind):
    a = SA.A.scan_sources({"x.py": src}, SA.A.collect_tokens(), SA.A.exempt_words())
    assert a["literal_hits"] == 1 and (a["branch_hits"] == 1) == (kind == "branch")


def test_token_scan_ignores_docstrings_but_reports_them():
    a = SA.A.scan_sources({"x.py": '"""mentions transfer_inventory"""\n'}, SA.A.collect_tokens(), SA.A.exempt_words())
    assert a["literal_hits"] == 0 and len(a["docstring_mentions"]) == 1


def test_identity_branch_scan_sees_a_tokenless_branch():
    src = "def f(eng):\n    if eng.model.package_id.startswith('manuf'):\n        return 1\n    return [x for x in y if x == eng.package_id]\n"
    hits = SA.identity_branches({"x.py": src})
    assert [h["name"] for h in hits] == ["package_id", "package_id"]
    assert SA.A.scan_sources({"x.py": src}, SA.A.collect_tokens(), SA.A.exempt_words())["literal_hits"] == 0  # the token scan alone is blind


def test_identity_branch_scan_is_quiet_on_plain_data_use():
    assert SA.identity_branches({"x.py": "def f(eng):\n    rec = {'package_id': eng.model.package_id}\n    return rec\n"}) == []


def test_oracles_import_no_engine_or_domain_code():
    from eoo_h20.run import FORBIDDEN_IMPORTS, oracle_facts
    facts = oracle_facts()
    assert len(facts) >= 3 and all(f["forbidden_imports"] == [] for f in facts)
    assert FORBIDDEN_IMPORTS == ("eoo_engine", "eoo_toolchain", "domains")


def test_oracle_import_checker_catches_a_planted_import(tmp_path, monkeypatch):
    from eoo_h20 import run as R
    d = tmp_path / "oracles/h20"
    d.mkdir(parents=True)
    (d / "bad.py").write_text("from eoo_engine import Engine\nimport domains.project.logic\n")
    monkeypatch.setattr(R, "ROOT", tmp_path)
    facts = R.oracle_facts()
    assert facts[0]["forbidden_imports"] == ["domains", "eoo_engine"]
