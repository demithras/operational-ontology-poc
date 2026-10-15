import copy
import itertools
import json

import pytest

from r3_shared.authspec import load_auth_spec
from r3_shared.governance import (MODELS, load_governance, structural_signature, structurally_distinct,
                                  validate_governance)
from r3_shared.opsspec import load_ops_spec
from tests.p1e_gen import DOMAINS, INVALID, gen_doc, ref_static_ok


@pytest.mark.parametrize("dom", DOMAINS)
@pytest.mark.parametrize("model", MODELS)
def test_fixtures_validate(model, dom):
    doc = load_governance(model, dom)
    assert validate_governance(doc, load_auth_spec(dom), load_ops_spec(dom)) is doc
    assert doc["model"] == model and doc["domain"] == dom


@pytest.mark.parametrize("dom", DOMAINS)
def test_three_models_are_pairwise_structurally_distinct(dom):
    sigs = {m: structural_signature(load_governance(m, dom)) for m in MODELS}
    for a, b in itertools.combinations(MODELS, 2):
        assert structurally_distinct(sigs[a], sigs[b]), (a, b)
    assert sigs["hierarchical"]["hierarchy"] == "chain" and sigs["collegial"]["hierarchy"] == "none"
    assert sigs["polycentric"]["hierarchy"] == "dag" and sigs["polycentric"]["concurrence"] is True


def test_not_distinct_known_negative_pair():
    d = load_governance("collegial", "project")
    twin = copy.deepcopy(d)
    twin["model"] = "collegial-renamed"
    for b in twin["bodies"]:
        b["members"] = list(reversed(b["members"]))
    assert not structurally_distinct(d, twin)
    one = copy.deepcopy(d)
    one["precedence"] = ["rank", "specialis"]  # differs in exactly ONE dimension
    assert not structurally_distinct(d, one)
    two = copy.deepcopy(one)
    two["superior"] = [["board-b", "board-a"]]  # + hierarchy none -> chain: two dimensions
    assert structurally_distinct(d, two)


def test_signature_is_pure_and_complete():
    s = structural_signature(load_governance("polycentric", "manufacturing"))
    assert set(s) == {"decision_rules", "hierarchy", "concurrence", "review", "lapse", "precedence", "emergency",
                      "max_body_size", "jurisdiction_overlap"}
    assert s["precedence"] == ("specialis", "rank") and s["decision_rules"] == ["quorum", "single"]
    assert s == structural_signature(load_governance("polycentric", "manufacturing"))


def _bad(mut):
    d = copy.deepcopy(load_governance("hierarchical", "manufacturing"))
    mut(d)
    return d


REJECT = {
    "cycle_in_superior": lambda d: d["superior"].append(["office-top", "office-lead"]),
    "k_gt_members": lambda d: None,  # replaced below (hierarchical has no quorum)
    "review_by_competent": lambda d: d["matters"][0]["review"].update(by="office-lead"),
    "case_state_key_present": lambda d: d.update(cases=[]),
    "static_delegate_member": lambda d: d["bodies"][0].update(members=["agent-1"]),
    "unknown_principal": lambda d: d["bodies"][0].update(members=["ghost"]),
    "duplicate_body": lambda d: d["bodies"].append(copy.deepcopy(d["bodies"][0])),
    "single_with_two_members": lambda d: d["bodies"][0]["members"].append("planner-1"),
    "window_zero": lambda d: d["matters"][0]["review"].update(window=0),
    "lapse_after_zero": lambda d: d["matters"][0].update(on_absent={"lapse": "deny", "after": 0}),
    "duplicate_precedence": lambda d: d.update(precedence=["rank", "rank"]),
    "emergency_scope_other_op": lambda d: d["matters"][-1]["scope"]["operations"].append("reschedule_work_order"),
    "ceiling_unknown_op": lambda d: d["emergency"]["ceiling"]["operations"].append("nope"),
    "emergency_matter_missing": lambda d: d["emergency"].update(matter="nope"),
    "wrong_spec_tag": lambda d: d.update(spec="r3-governance-0"),
    "superior_unknown_body": lambda d: d["superior"].append(["office-lead", "ghost"]),
    "matter_without_competent": lambda d: d["matters"][0].update(competent=[]),
    "extra_key_in_body": lambda d: d["bodies"][0].update(votes=[]),
}


@pytest.mark.parametrize("name", [n for n in REJECT if n != "k_gt_members"])
def test_reject_table(name):
    with pytest.raises(ValueError):
        validate_governance(_bad(REJECT[name]), load_auth_spec("manufacturing"), load_ops_spec("manufacturing"))


def test_k_greater_than_members_and_k_zero_rejected():
    for k in (0, 4):
        d = copy.deepcopy(load_governance("collegial", "manufacturing"))
        d["bodies"][0]["rule"]["k"] = k
        with pytest.raises(ValueError):
            validate_governance(d, load_auth_spec("manufacturing"), load_ops_spec("manufacturing"))


def test_parity_with_independent_reference_on_2000_generated_docs():
    accepted = rejected = 0
    for seed in range(2000):
        doc, auth, ops, names = gen_doc(seed)
        try:
            validate_governance(doc, auth, ops)
            got = True
        except ValueError:
            got = False
        assert got == ref_static_ok(doc, auth, ops), (seed, names)
        accepted += got
        rejected += not got
    assert accepted > 300 and rejected > 300  # both classes are exercised (non-vacuity)


def test_every_generator_invalid_mutation_is_rejected_at_least_once():
    seen = set()
    for seed in range(2000):
        doc, auth, ops, names = gen_doc(seed)
        try:
            validate_governance(doc, auth, ops)
        except ValueError:
            seen.update(names)
    assert {f.__name__ for f in INVALID} <= seen | {"_case_key"}  # _case_key must too:
    assert "_case_key" in seen


def test_document_is_plain_json_and_fixtures_are_canonical_files():
    for m in MODELS:
        for d in DOMAINS:
            raw = open(f"spec/governance/{m}.{d}.json").read()
            assert json.loads(raw) == load_governance(m, d) and raw.endswith("\n")
