"""compile(render(ir)) == ir exactly (and equivalent under the oracle); the record carries atoms only:
alpha-renaming of atoms and of addresses, and a record that holds nothing but its own keys."""
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eoo_ir import equivalent, validate
from eoo_ir.strategies import valid_packages
from eoo_openpona import compile as op_compile, load_record, render

from openpona_util import (ROOT, load, map_addresses, numeric_placeholders, random_address_bijection,
                           rename_atoms, shape)

FILES = ["domains/manufacturing/ir.json", "domains/project/ir.json", "tests/h15/openpona_coverage_ir.json",
         "ontology/examples/manufacturing-minimal.json", "ontology/examples/project-domain-minimal.json"]


def _roundtrip(ir):
    text, rec = render(ir)
    out = op_compile(text, rec)
    assert json.dumps(out, sort_keys=True) == json.dumps(ir, sort_keys=True)
    assert equivalent(ir, out).ok
    assert validate(out) == []
    assert render(out) == (text, rec)
    return text, rec


@pytest.mark.parametrize("path", FILES)
def test_file_round_trips_exactly(path):
    _roundtrip(load(path))


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_committed_domain_text_compiles_to_the_frozen_ir(domain):
    ir = load(f"domains/{domain}/ir.json")
    text = (ROOT / f"domains/{domain}/openpona.op").read_text()
    rec = load_record((ROOT / f"domains/{domain}/openpona.record.json").read_text())
    out = op_compile(text, rec)
    assert out == ir and equivalent(ir, out).ok


@given(valid_packages())
def test_generated_packages_round_trip_exactly(pkg):
    _roundtrip(pkg)


def _alpha_atoms(ir):
    text, rec = render(ir)
    renamed = rename_atoms(text, rec, lambda k: "α" + k)
    out = op_compile(text, renamed)
    assert render(out) == (text, renamed)  # same lines: the structure did not move into the record
    return text, out


@pytest.mark.parametrize("path", FILES)
def test_alpha_renaming_atoms_keeps_every_line(path):
    _alpha_atoms(load(path))


@settings(max_examples=60)
@given(valid_packages())
def test_alpha_renaming_atoms_generated(pkg):
    _alpha_atoms(pkg)


def _line_only(ir):
    """The record holds nothing but its own keys (numeric literals: a constant): the IR shape survives."""
    text, rec = render(ir)
    out = op_compile(text, numeric_placeholders(text, rec), check_ir=False)
    assert shape(out) == shape(ir)


@pytest.mark.parametrize("path", FILES)
def test_line_only_shape(path):
    _line_only(load(path))


@settings(max_examples=60)
@given(valid_packages())
def test_line_only_shape_generated(pkg):
    _line_only(pkg)


def _address_bijection(ir, seed):
    text, rec = render(ir)
    mapping = random_address_bijection(text, seed)
    assert op_compile(map_addresses(text, mapping.__getitem__), rec) == ir


@pytest.mark.parametrize("path", FILES)
def test_addresses_are_coreference_only(path):
    for seed in range(3):
        _address_bijection(load(path), seed)


@settings(max_examples=60)
@given(valid_packages(), st.integers(0, 10**6))
def test_addresses_are_coreference_only_generated(pkg, seed):
    _address_bijection(pkg, seed)


def test_line_only_shape_check_has_teeth():
    """Known-negative: a record that changes structure-looking atoms cannot change the shape, but a line edit does."""
    ir = load("ontology/examples/manufacturing-minimal.json")
    text, rec = render(ir)
    edited = text.replace(" li wile\n", " li wile ala\n", 1)
    out = op_compile(edited, rec)
    assert shape(out) != shape(ir)
