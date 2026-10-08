import copy

import pytest

from r3_shared.authgraph import authority_digest, authority_document
from r3_shared.authspec import effective_disclosure, load_auth_spec, validate_strict
from r3_shared.opsspec import load_ops_spec

RULE = {"id": "r1", "effect": "allow", "principal": {"role": "planner"},
        "object": {"type": "WorkOrder", "keys": None, "via": None},
        "reveals": {"exists": True, "fields": ["status"], "links": ["WorkOrder_warehouse"], "provenance": "scalars"}}


def v3(dom="manufacturing", **disc):
    s = copy.deepcopy(load_auth_spec(dom))
    s.update(spec="r3-authority-3", max_delegation_depth=4, capabilities=[], revoked=[],
             disclosure={"public_types": ["Warehouse"], "public_links": [], "rules": [copy.deepcopy(RULE)], **disc})
    return s


@pytest.fixture(scope="module")
def ops():
    return load_ops_spec("manufacturing")


def test_valid_v3_passes_and_graph_rules_still_run(ops):
    assert validate_strict(v3(), ops)["spec"] == "r3-authority-3"
    s = v3()
    s["capabilities"] = [{"id": "e1", "issuer": "planner-1", "child": "agent-1", "parent": None,
                          "scope": {"operations": ["reschedule_work_order"], "resources": []}, "expires_at": None,
                          "redelegable": False, "issued_at": 0}]
    with pytest.raises(ValueError, match="static delegate"):
        validate_strict(s, ops)


def _mut(f):
    s = v3()
    f(s["disclosure"])
    return s


REJECT = {
    "duplicate_rule_ids": lambda d: d["rules"].append(copy.deepcopy(RULE)),
    "unknown_type": lambda d: d["rules"][0]["object"].update(type="Nope"),
    "unknown_field": lambda d: d["rules"][0]["reveals"].update(fields=["nope"]),
    "unknown_link_in_reveals": lambda d: d["rules"][0]["reveals"].update(links=["nope"]),
    "unknown_public_type": lambda d: d["public_types"].append("Nope"),
    "unknown_public_link": lambda d: d["public_links"].append("nope"),
    "via_unknown_type": lambda d: d["rules"][0]["object"].update(via={"link": "WorkOrder_warehouse", "dir": "out", "type": "Nope"}),
    "via_unknown_link": lambda d: d["rules"][0]["object"].update(via={"link": "nope", "dir": "out", "type": "Warehouse"}),
    "via_bad_dir": lambda d: d["rules"][0]["object"].update(via={"link": "WorkOrder_warehouse", "dir": "up", "type": "Warehouse"}),
    "provenance_not_in_enum": lambda d: d["rules"][0]["reveals"].update(provenance="all"),
    "effect_not_in_enum": lambda d: d["rules"][0].update(effect="maybe"),
    "extra_rule_key": lambda d: d["rules"][0].update(note="x"),
    "extra_disclosure_key": lambda d: d.update(note=1),
    "missing_reveals_key": lambda d: d["rules"][0]["reveals"].pop("exists"),
    "unknown_principal_id": lambda d: d["rules"][0].update(principal={"id": "ghost"}),
}


@pytest.mark.parametrize("name", sorted(REJECT))
def test_v3_reject_table(name, ops):
    with pytest.raises(ValueError):
        validate_strict(_mut(REJECT[name]), ops)


def test_missing_disclosure_member_rejected(ops):
    s = v3()
    del s["disclosure"]
    with pytest.raises(ValueError):
        validate_strict(s, ops)


def test_via_rule_and_wildcard_fields_accepted(ops):
    s = v3()
    s["disclosure"]["rules"].append({**copy.deepcopy(RULE), "id": "r2", "effect": "deny",
        "object": {"type": "Part", "keys": ["PX-17"], "via": {"link": "BomRequirement_requiresPart", "dir": "in", "type": "BomRequirement"}},
        "reveals": {"exists": False, "fields": "*", "links": [], "provenance": "none"}})
    validate_strict(s, ops)


def test_v2_in_force_behaves_as_all_public(ops):
    s2 = copy.deepcopy(v3())
    s2["spec"] = "r3-authority-2"
    del s2["disclosure"]
    d = effective_disclosure(s2, ops)
    assert set(d["public_types"]) == {t["name"] for t in ops["resource_types"]}
    assert set(d["public_links"]) == {l["name"] for l in ops["link_types"]} and d["rules"] == []
    assert effective_disclosure(load_auth_spec("manufacturing"), ops)["rules"] == []
    assert effective_disclosure(v3(), ops) == v3()["disclosure"]


def test_disclosure_is_covered_by_authority_digest():
    a, b = v3(), v3()
    assert authority_digest(a) == authority_digest(b)
    b["disclosure"]["rules"][0]["reveals"]["exists"] = False
    assert authority_digest(a) != authority_digest(b)
    assert authority_document(a)["disclosure"] == a["disclosure"]
    unordered = v3()
    unordered["revoked"] = []
    assert authority_document(unordered)["revoked"] == []


def test_v1_and_v2_fixtures_unchanged_behaviour(ops):
    for d in ("manufacturing", "project"):
        validate_strict(load_auth_spec(d), load_ops_spec(d))
    s2 = copy.deepcopy(v3())
    s2["spec"] = "r3-authority-2"
    del s2["disclosure"]
    validate_strict(s2, ops)
    s2["disclosure"] = {}
    validate_strict(s2, ops)  # v2 schema does not forbid extra keys (unchanged)
