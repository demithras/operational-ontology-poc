"""H15 v2: every declared ambiguity / missing-type case fails closed with the declared typed error; >= 3 cases for
every class of protocol/h15_ambiguity_classes.json; line-deletion mutants never invent semantics."""
import json
from collections import Counter

import pytest

import eoo_openpona2 as op2
from eoo_h15 import ambiguity, candidate

from openpona_util import ROOT, load

CASES = [json.loads(x) for x in (ROOT / "tests/h15/openpona2_ambiguity_cases.jsonl").read_text().splitlines()]
CLASSES = {c["id"]: c["expected"] for c in load("protocol/h15_ambiguity_classes.json")["classes"]}


def test_every_class_has_at_least_three_cases():
    n = Counter(c["class"] for c in CASES)
    assert set(n) == set(CLASSES), set(CLASSES) ^ set(n)
    assert min(n.values()) >= 3, n


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_declared_case_fails_closed_as_declared(case):
    with pytest.raises(op2.OpenPonaError) as ei:
        rec = op2.load_record(case["record_json"]) if "record_json" in case else case["record"]
        op2.compile(case["text"], rec)
    assert (type(ei.value).__name__, ei.value.code) == (case["error"], case["code"])
    if CLASSES[case["class"]] == "unresolved":
        assert isinstance(ei.value, op2.Unresolved)


@pytest.fixture
def v2():
    candidate.use("openpona2")
    yield
    candidate.use("openpona")


def test_harness_declared_summary_for_v2(v2):
    s = ambiguity.declared_openpona()
    assert s["total"] == len(CASES) and s["as_declared"] == s["total"] and not s["accepted"] and not s["crashed"]


def test_line_deletion_mutants_never_invent_semantics(v2):
    acc = ambiguity._new()
    for rel in ("tests/h15/openpona_coverage_ir.json", "ontology/examples/project-domain-minimal.json"):
        ambiguity.op_deletions(load(rel), rel, acc)
    d = ambiguity._fin(acc)
    assert d["total"] > 300 and d["violations"] == 0, (d["invented"], d["crashed"])
    assert d["raised"] > d["accepted_exact"] > 0


def test_nested_type_inner_deletion_is_accepted_exactly_as_stated():
    """Recorded judgment call 2: deleting the inner constructor of {list: {optional: T}} yields {optional: T}, which the
    mutant fully states; it is accepted, never guessed."""
    ir = {"package_id": "p", "version": "1", "object_types": [{"id": "O", "primary_key": "a", "implements": [],
          "properties": [{"name": "a", "type": {"list": {"optional": "string"}}, "required": True}]}],
          "link_types": [], "interfaces": [], "functions": [], "actions": [], "policies": [], "authority_rules": [],
          "observation_types": [], "constraints": []}
    text, rec = op2.render(ir)
    lines = text.splitlines()
    i = lines.index("nasin li linja e nasin")
    from eoo_h15.opdoc import delete_line
    mt, mr = delete_line(text, rec, i + 1)
    out = op2.compile(mt, mr)
    assert out["object_types"][0]["properties"][0]["type"] == {"optional": "string"}
