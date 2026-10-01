"""Hand-written pairs that differ in ONE thing; the oracle must say non-equivalent and name the field."""
import copy
import json
from pathlib import Path

import pytest

from eoo_ir import equivalent

ROOT = Path(__file__).resolve().parents[2]
MANU = json.loads((ROOT / "ontology/examples/manufacturing-minimal.json").read_text())
PROJ = json.loads((ROOT / "ontology/examples/project-domain-minimal.json").read_text())


def variant(base, fn):
    b = copy.deepcopy(base)
    fn(b)
    return base, b


def _function_to_action(b):
    f = b["functions"][0]
    b["functions"].remove(f)
    b["actions"].append({"id": f["id"], "inputs": f["inputs"], "authority_refs": [], "policy_refs": [], "preconditions": [],
                         "effects": [{"target": "X", "operation": "external_call"}], "idempotency": "not_applicable",
                         "outcome_predicate": "p", "version": "v1"})


CASES = {
    "cardinality_max_1_vs_star": (variant(PROJ, lambda b: b["link_types"][0]["to_cardinality"].update(max="*")), "to_cardinality.max"),
    "function_vs_action_same_id": (variant(MANU, _function_to_action), "functions[available_quantity]"),
    "authority_allow_vs_deny": (variant(MANU, lambda b: b["authority_rules"][0].update(effect="deny")), "authority_rules[inventory-transfer].effect"),
    "dropped_package_version": (variant(MANU, lambda b: b.pop("version")), "version"),
    "dropped_action_version": (variant(MANU, lambda b: b["actions"][0].pop("version")), "actions[transfer_inventory].version"),
    "dropped_policy_version": (variant(PROJ, lambda b: b["policies"][0].pop("version")), "policies[preregistration-complete].version"),
    "required_true_vs_false": (variant(MANU, lambda b: b["object_types"][0]["properties"][1].update(required=False)),
                               "object_types[InventoryLot].properties[quantity].required"),
    "optional_vs_nonoptional_type": (variant(MANU, lambda b: b["object_types"][0]["properties"][1].update(type={"optional": "integer"})),
                                     "object_types[InventoryLot].properties[quantity].type"),
    "absent_vs_null_compensation": (variant(MANU, lambda b: b["actions"][0].pop("compensation_action")), "compensation_action"),
    "bool_true_vs_int_one_in_metadata": (variant({**MANU, "metadata": {"k": True}}, lambda b: b["metadata"].update(k=1)), "metadata.k"),
    "effect_order": (variant(PROJ, lambda b: b["actions"][0]["effects"].extend(
        [{"target": "A", "operation": "external_call"}, {"target": "B", "operation": "external_call"}])), "effects"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_known_negative(name):
    (a, b), marker = CASES[name]
    res = equivalent(a, b)
    assert not res.ok, name
    assert any(marker in d for d in res.diffs), (name, res.diffs)


def test_input_and_effect_order_are_significant_but_set_lists_are_not():
    base = copy.deepcopy(MANU)
    sw = copy.deepcopy(base)
    sw["actions"][0]["inputs"].reverse()
    assert not equivalent(base, sw).ok  # inputs are positional
    st = copy.deepcopy(base)
    st["actions"][0]["preconditions"].reverse()
    assert equivalent(base, st).ok  # preconditions are a set
    d = copy.deepcopy(base)
    d["actions"][0]["preconditions"].append(d["actions"][0]["preconditions"][0])
    assert not equivalent(base, d).ok  # duplicates are KEPT


def test_defaults_expand_but_absent_stays_absent():
    base = copy.deepcopy(MANU)
    ex = copy.deepcopy(base)
    ex["object_types"][0]["properties"][0].pop("immutable")  # default false is not what the file says (true) -> differs
    assert not equivalent(base, ex).ok
    ex2 = copy.deepcopy(base)
    ex2["object_types"][0]["properties"][1].pop("immutable")  # explicit false -> default false: equivalent
    assert equivalent(base, ex2).ok
    nodet = copy.deepcopy(base)
    nodet["functions"][0].pop("determinism")  # no default exists: must NOT be filled
    assert not equivalent(base, nodet).ok
