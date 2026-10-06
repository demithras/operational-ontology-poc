"""The oracle shares no implementation with the Toolchain / Engine / domains; the Toolchain never loads the oracle."""
import ast
import shutil
from pathlib import Path

from domains._pack import load_ir
from eoo_h21 import static

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FOR_ORACLE = {"eoo_engine", "eoo_engine_git", "eoo_toolchain", "domains", "eoo_h21", "eoo_ir", "hdd", "eoo_exp"}


def test_oracle_imports_nothing_from_engine_toolchain_or_domains():
    files = sorted((ROOT / "oracles/h21").glob("*.py"))
    assert [f.name for f in files] == ["__init__.py", "authority_oracle.py", "typecheck_oracle.py"]
    for f in files:
        assert set(static.imports_of(f.read_text())) & FORBIDDEN_FOR_ORACLE == set(), f.name
        assert "eoo_toolchain" not in f.read_text().replace("Toolchain", "")  # no textual reach either


def test_toolchain_never_imports_or_loads_the_oracle_or_engine():
    f = static.toolchain_facts()
    assert f["imports_oracle"] is False and f["forbidden_imports"] == [] and len(f["files"]) >= 8


def test_import_checker_known_negatives(tmp_path):
    shutil.copy(ROOT / "src/eoo_toolchain/naming.py", tmp_path / "naming.py")
    (tmp_path / "bad1.py").write_text("from oracles.h21 import authority_oracle\n")
    (tmp_path / "bad2.py").write_text("import eoo_engine\n")
    (tmp_path / "bad3.py").write_text("import importlib\nimportlib.import_module('oracles.h21.authority_oracle')\n")
    f = static.toolchain_facts(tmp_path)
    assert f["imports_oracle"] is True and "eoo_engine" in f["forbidden_imports"]
    assert {r["file"] for r in f["files"] if r["forbidden_imports"]} == {"bad1.py", "bad2.py"}
    only3 = tmp_path / "only3"
    only3.mkdir()
    (only3 / "bad3.py").write_text((tmp_path / "bad3.py").read_text())
    assert static.toolchain_facts(only3)["imports_oracle"] is True  # the dynamic-import form alone is caught too


def test_toolchain_source_has_no_domain_identifiers(tmp_path):
    irs = [load_ir("manufacturing"), load_ir("project")]
    assert static.domain_token_scan(irs)["hits"] == {}
    (tmp_path / "x.py").write_text("T = 'transfer_inventory'\nU = 'Hypothesis'\n")
    assert static.domain_token_scan(irs, tmp_path)["hits"] == {"x.py": ["Hypothesis", "transfer_inventory"]}


def test_generated_text_is_the_only_place_domain_ids_appear(built):
    ir, d, inv, *_ = built["manufacturing"]
    text = "".join((d / inv["package"] / fn).read_text() for fn in inv["files"])
    assert "transfer_inventory" in text and ast.parse((d / inv["package"] / "sdk.py").read_text())
