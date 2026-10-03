"""H15 v2 round trip and audit_procedure_v2 on fixed IRs and generated packages (dev profile; the frozen run is the
experiment's job). Includes known-negatives that prove the audit can fail."""
import json

import pytest
from hypothesis import given

import eoo_openpona2 as op2
import eoo_openpona2.ctx as ctx2
from eoo_ir import equivalent
from eoo_ir.strategies import valid_packages
from eoo_h15 import sidecar2
from eoo_h15.isolation import isolated_constants
from eoo_h15.util import canon

from openpona_util import ROOT, load

FIXED = ["domains/manufacturing/ir.json", "domains/project/ir.json", "tests/h15/openpona_coverage_ir.json",
         "ontology/examples/manufacturing-minimal.json", "ontology/examples/project-domain-minimal.json"]


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_irs_round_trip_exactly_and_pass_the_v2_audit(rel):
    ir = load(rel)
    text, rec = op2.render(ir)
    assert canon(op2.compile(text, rec)) == canon(ir)
    a = sidecar2.audit_package(ir, text, rec)
    assert a["alpha"]["ok"], a["alpha"]
    assert a["shape"]["ok"], a["shape"]
    assert a["vocabulary"]["ok"], a["vocabulary"]


def _prop(pkg):
    text, rec = op2.render(pkg)
    out = op2.compile(text, rec)
    assert equivalent(pkg, out).ok and canon(out) == canon(pkg)
    a = sidecar2.audit_package(pkg, text, rec)
    assert a["alpha"]["ok"] and a["shape"]["ok"] and a["vocabulary"]["ok"], (a["alpha"], a["shape"])


def test_generated_packages_round_trip_and_pass_the_audit():
    with isolated_constants():
        given(valid_packages())(_prop)()


def test_alpha_rename_known_negative_value_sniffing_compiler(monkeypatch):
    """A compiler that reads a structural flag from an atom's VALUE (id length parity -> required) must fail the audit."""
    ir = load("tests/h15/openpona_coverage_ir.json")
    text, rec = op2.render(ir)
    orig = ctx2._C.one

    def sniffing(self, k, f, required=True):
        if f == "required" and k[0] == "prop":
            return len(k[3]) % 2 == 0
        return orig(self, k, f, required)
    monkeypatch.setattr(ctx2._C, "one", sniffing)
    a = sidecar2.audit_package(ir, text, rec)
    assert not (a["alpha"]["ok"] and a["shape"]["ok"]), "audit did not notice structure read from atom values"


def test_shape_known_negative_coreference_by_line_position(monkeypatch):
    """Known-negative for the value-consistent placeholders: unique-per-slot placeholders break coreference (equal ids
    no longer equal), so the v1-style unique placeholder test must FAIL on v2 -- coreference really lives in the atoms."""
    ir = load("ontology/examples/manufacturing-minimal.json")
    text, rec = op2.render(ir)
    unique = {k: f"U{i}" for i, k in enumerate(rec)}
    with pytest.raises(op2.OpenPonaError):
        op2.compile(text, unique)


def test_renaming_one_occurrence_breaks_coreference_fail_closed():
    ir = load("ontology/examples/manufacturing-minimal.json")
    text, rec = op2.render(ir)
    k = next(k for k in rec if rec[k] == "InventoryLot" and k != "L7.a1")
    with pytest.raises(op2.OpenPonaError):
        op2.compile(text, {**rec, k: "InventoryLotX"})


def test_record_vocabulary_flags_a_structural_key():
    ir = load("ontology/examples/manufacturing-minimal.json")
    text, rec = op2.render(ir)
    assert sidecar2.record_vocabulary(text, rec)["ok"]
    assert not sidecar2.record_vocabulary(text, {**rec, "kind": "function"})["ok"]
    assert not sidecar2.record_vocabulary(text, {**rec, "L4.a1": "x"})["ok"]
