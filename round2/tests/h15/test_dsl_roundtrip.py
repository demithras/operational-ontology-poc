"""compile(render(ir)) must reproduce the IR exactly (not merely equivalently) and be equivalent under the oracle."""
import json
from pathlib import Path

import pytest
from hypothesis import given

from eoo_dsl import compile as dsl_compile, render
from eoo_ir import equivalent, validate
from eoo_ir.strategies import valid_packages

ROOT = Path(__file__).resolve().parents[2]


@given(valid_packages())
def test_generated_packages_round_trip_exactly(pkg):
    text = render(pkg)
    out = dsl_compile(text)
    assert json.dumps(out, sort_keys=True) == json.dumps(pkg, sort_keys=True), text[:3000]
    assert equivalent(pkg, out).ok
    assert validate(out) == []
    assert render(out) == text  # render is a function of the IR only


@pytest.mark.parametrize("path", sorted((ROOT / "ontology" / "examples").glob("*.json")))
def test_frozen_examples_round_trip(path):
    ir = json.loads(path.read_text())
    out = dsl_compile(render(ir))
    assert out == ir and equivalent(ir, out).ok


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_committed_dsl_matches_ir(domain):
    ir = json.loads((ROOT / "domains" / domain / "ir.json").read_text())
    text = (ROOT / "domains" / domain / "dsl.yaml").read_text()
    assert text == render(ir), "dsl.yaml is stale: regenerate with scripts/build_domain_ir.py"
    out = dsl_compile(text)
    assert out == ir
    assert equivalent(ir, out).ok
