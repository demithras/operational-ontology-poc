"""R1/R2/R3: pinned unmodified parser; every rendered line RESOLVED; record keys neutral, values atoms."""
import ast
import hashlib
import json
import re
from importlib.metadata import distribution
from pathlib import Path

import openpona
import pytest
from hypothesis import given
from openpona.parser import parse

from eoo_ir.strategies import valid_packages
from eoo_openpona import render
from eoo_openpona.lines import read_line
from eoo_openpona.templates import T

from openpona_util import ROOT, load

PIN = json.loads((ROOT / "hypotheses/h15/contract.json").read_text())["experiment"]["openpona_pin"]
KEY = re.compile(r"L[1-9][0-9]*\.a[1-9][0-9]*")
SOURCES = {"manufacturing": "domains/manufacturing/ir.json", "project": "domains/project/ir.json",
           "coverage": "tests/h15/openpona_coverage_ir.json",
           "example-m": "ontology/examples/manufacturing-minimal.json",
           "example-p": "ontology/examples/project-domain-minimal.json"}


def test_installed_at_pinned_commit():
    du = json.loads(distribution("openpona-language-corpus").read_text("direct_url.json"))
    assert du["url"] == PIN["repository"]
    assert du["vcs_info"]["commit_id"].startswith(PIN["commit"]) and len(du["vcs_info"]["commit_id"]) == 40


def test_installed_token_inventory_and_grammar_match_the_pin():
    pkg = Path(openpona.__file__).parent
    assert hashlib.sha256((pkg / "tokens.csv").read_bytes()).hexdigest() == PIN["tokens_csv_sha256"]
    assert hashlib.sha256((pkg / "grammar.lark").read_bytes()).hexdigest() == PIN["grammar_lark_sha256"]
    assert len(openpona.TOKENS) == 42


def test_surface_code_never_patches_the_parser():
    """R1: only `parse` and the token lists are imported; nothing assigns into the openpona package."""
    for path in sorted((ROOT / "src/eoo_openpona").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("openpona"):
                assert (node.module, [a.name for a in node.names]) in (("openpona.parser", ["parse"]), ("openpona", ["SEMANTIC"])), path
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("openpona") for a in node.names), path
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    assert "openpona" not in ast.unparse(t) and "parse" != ast.unparse(t), (path, ast.unparse(t))
        assert "setattr" not in path.read_text() and "monkeypatch" not in path.read_text(), path


def _check_render(text: str, rec: dict):
    lines = text.splitlines()
    assert lines and text.endswith("\n")
    for i, ln in enumerate(lines, 1):
        r = parse(ln)
        assert r.status == "RESOLVED", (i, ln, r.status, r.errors)
        assert not any(re.search(r"D\d+\(", s) for s in r.skeletons), (i, ln)  # no META anywhere
        assert all(t in openpona.TOKENS for t in r.tokens)
    for k, v in rec.items():
        assert KEY.fullmatch(k), k
        assert isinstance(v, str)
        assert int(k[1:].split(".")[0]) <= len(lines)


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_every_rendered_line_resolves_and_record_is_neutral(name):
    _check_render(*render(load(SOURCES[name])))


@given(valid_packages())
def test_generated_renders_resolve_and_records_are_neutral(pkg):
    _check_render(*render(pkg))


def test_committed_domain_files_are_fresh_and_resolve():
    for d in ("manufacturing", "project"):
        text, rec = render(load(f"domains/{d}/ir.json"))
        assert (ROOT / f"domains/{d}/openpona.op").read_text() == text
        assert json.loads((ROOT / f"domains/{d}/openpona.record.json").read_text()) == rec
        _check_render(text, rec)


def test_encoding_table_examples_parse_resolved_and_match_their_rule():
    md = (ROOT / "ontology/openpona_encoding.md").read_text()
    rows = [ln for ln in md.splitlines() if ln.startswith("| `") and ln.count("|") >= 7]
    seen = set()
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        tid, example = cells[0].strip("`"), cells[-1].strip("`")
        if tid not in T:
            continue
        assert parse(example).status == "RESOLVED", example
        assert read_line(1, example).tid == tid, (tid, example)
        seen.add(tid)
    assert seen == set(T), set(T) - seen


def test_every_rule_is_exercised_by_the_coverage_fixture():
    seen = set()
    for src in ("tests/h15/openpona_coverage_ir.json", "ontology/examples/manufacturing-minimal.json"):
        text, _ = render(load(src))
        seen |= {read_line(i, ln).tid for i, ln in enumerate(text.splitlines(), 1)}
    assert set(T) - seen <= {"pkg.meta_empty"}, set(T) - seen
