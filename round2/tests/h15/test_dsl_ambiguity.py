"""Every ambiguity class, instantiated for the DSL baseline, fails closed with the declared typed error."""
import json
from collections import Counter
from pathlib import Path

import pytest

import eoo_dsl.errors as errors
from eoo_dsl import DslError, compile as dsl_compile, render

ROOT = Path(__file__).resolve().parents[2]
CLASSES = json.loads((ROOT / "protocol" / "h15_ambiguity_classes.json").read_text())
CASES = [json.loads(line) for line in (ROOT / "tests" / "h15" / "dsl_ambiguity_cases.jsonl").read_text().splitlines()]
BASES = {name: render(json.loads((ROOT / "ontology" / "examples" / f"{f}.json").read_text()))
         for name, f in (("M", "manufacturing-minimal"), ("P", "project-domain-minimal"))}
EXPECTED = {c["id"]: c["expected"] for c in CLASSES["classes"]}


def test_every_class_has_at_least_two_cases():
    n = Counter(c["class"] for c in CASES)
    assert set(n) == set(EXPECTED), set(EXPECTED) ^ set(n)
    assert all(v >= 2 for v in n.values()), n


def test_case_ids_unique_and_declared_expectation_matches_class():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c["expected"] == EXPECTED[c["class"]], c["id"]
        assert c["expected"] in ("error", "unresolved")


@pytest.mark.parametrize("base", ["M", "P"])
def test_control_unmutated_base_compiles(base):
    """Known-positive control: the cases below fail because of their edit, not because the base is broken."""
    assert dsl_compile(BASES[base])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_fails_closed(case):
    assert case["text"] != BASES[case["base"]]
    expected = getattr(errors, case["dsl_error"])
    with pytest.raises(DslError) as ei:
        dsl_compile(case["text"])
    assert isinstance(ei.value, expected), (type(ei.value).__name__, str(ei.value))
    if case["expected"] == "unresolved":
        assert isinstance(ei.value, errors.DslUnresolvedReference)
