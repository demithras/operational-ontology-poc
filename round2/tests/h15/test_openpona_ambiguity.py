"""Every ambiguity class, instantiated for the OpenPona surface (>= 3 cases each), fails closed with the
declared typed error and rule code; 'unresolved' cases raise Unresolved."""
import json
from collections import Counter

import pytest

import eoo_openpona.errors as errors
from eoo_openpona import compile as op_compile, load_record, render

from openpona_util import ROOT, load

CLASSES = json.loads((ROOT / "protocol" / "h15_ambiguity_classes.json").read_text())
EXPECTED = {c["id"]: c["expected"] for c in CLASSES["classes"]}
CASES = [json.loads(x) for x in (ROOT / "tests/h15/openpona_ambiguity_cases.jsonl").read_text().splitlines()]
BASES = {"M": "ontology/examples/manufacturing-minimal.json", "P": "ontology/examples/project-domain-minimal.json",
         "C": "tests/h15/openpona_coverage_ir.json"}


def test_every_class_has_at_least_three_cases():
    n = Counter(c["class"] for c in CASES)
    assert set(n) == set(EXPECTED), set(EXPECTED) ^ set(n)
    assert all(v >= 3 for v in n.values()), n


def test_case_ids_unique_and_expectation_matches_class():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c["expected"] == EXPECTED[c["class"]], c["id"]
        assert (c["error"] == "Unresolved") == (c["expected"] == "unresolved"), c["id"]


@pytest.mark.parametrize("base", sorted(BASES))
def test_control_unmutated_base_compiles(base):
    """Known-positive control: each case fails because of its edit, not because the base is broken."""
    ir = load(BASES[base])
    text, rec = render(ir)
    assert op_compile(text, rec) == ir


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_fails_closed(case):
    text, rec = render(load(BASES[case["base"]]))
    assert (case["text"], case.get("record_json", case["record"])) != (text, rec)
    with pytest.raises(errors.OpenPonaError) as ei:
        record = load_record(case["record_json"]) if "record_json" in case else case["record"]
        op_compile(case["text"], record)
    assert type(ei.value).__name__ == case["error"], (type(ei.value).__name__, str(ei.value))
    assert ei.value.code == case["code"], str(ei.value)
    assert not isinstance(ei.value, errors.Unrepresentable)
