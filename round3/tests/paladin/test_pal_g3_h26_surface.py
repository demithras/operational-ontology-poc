"""H26 surface semantics: frozen check order (3.2), hidden == absent on mutating calls, tools exactness (3.4), low-view
fixpoint rules (s1-s2), hidden edges, determinism (s5)."""
import json

import pytest

from g2_rig import G2Rig, edge, v2_mfg
from g3_pairs import battery
from g3_rig import G3Rig
from paladin import capgraph
from paladin.sovview import low_view
from r3_shared.authspec import allowed_operations, effective_disclosure
from r3_shared.disclosure import check_low_result, tool_schema


@pytest.fixture
def rig(tmp_path):
    return G3Rig(tmp_path, v3=True)


# ---- 3.2 token -> schema -> authority -> existence/rules ------------------------------------------------------------------
def test_check_order_on_mutating_calls(rig):
    d = rig.dep
    assert d.direct("garbage", "start_run", {"hypothesis": "H-NOPE"}, request_id="o1").body == {"reason": "token"}
    # schema first: even a caller with no authority gets INVALID schema for a malformed request
    assert d.direct(rig.tok("viewer-1"), "start_run", {"hypothesis": 5}, request_id="o2").body == {"reason": "schema"}
    assert d.direct(rig.tok("viewer-1"), "start_run", {"nope": 1}, request_id="o3").body == {"reason": "schema"}
    # authority next: hidden-and-existing == absent for a caller with no authority
    a = d.direct(rig.tok("viewer-1"), "start_run", {"hypothesis": "H-A"}, request_id="o4")
    b = d.direct(rig.tok("viewer-1"), "start_run", {"hypothesis": "H-NOPE"}, request_id="o5")
    assert (a.status, a.body) == (b.status, b.body) == ("DENIED", {"reason": "authority"})
    # existence last, for an authorised caller
    c = d.direct(rig.tok("researcher-1"), "start_run", {"hypothesis": "H-NOPE"}, request_id="o6")
    assert (c.status, c.body) == ("INVALID", {"reason": "not_found"})
    e = d.direct(rig.tok("researcher-1"), "start_run", {"hypothesis": "H-A"}, request_id="o7")
    assert (e.status, e.body) == ("DENIED", {"reason": "policy"})        # G3-E17: deny rules -> existence -> preconditions; here a deny rule fires


def test_refusal_bodies_carry_only_a_reason(rig):
    probes = [rig.dep.direct(rig.tok("researcher-1"), "start_run", {"hypothesis": "H-A"}, request_id="p1"),
              rig.dep.call_tool(rig.tok("viewer-1"), "start_run", {"hypothesis": "H-A"}, request_id="p2"),
              rig.dep.direct(rig.tok("researcher-1"), "edit_threshold", {"threshold": "T-A", "value": 1}, request_id="p3"),
              rig.dep.delegate(rig.tok("viewer-1"), {"id": "x"}, "p4"), rig.dep.revoke(rig.tok("viewer-1"), "nope", "p5"),
              rig.dep.approve(rig.tok("viewer-1"), "start_run", {"hypothesis": "H-A"}, "researcher-1")]
    for res in probes:
        assert res.status != "OK" and set(res.body) == {"reason"} and isinstance(res.body["reason"], str), res


def test_ok_bodies_use_ids_derived_from_the_request_id(rig):
    res = rig.dep.direct(rig.tok("researcher-1"), "create_hypothesis", {"claim": "x"}, request_id="rq-1")
    assert res.status == "OK" and res.body["execution"] == "x:rq-1" and res.body["effects"] == ["x:rq-1/e0"]


# ---- 3.4 tools ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("domain", ["project", "manufacturing"])
def test_tools_are_exactly_the_allowed_operations_with_the_frozen_schema(tmp_path, domain):
    r = G3Rig(tmp_path, domain=domain, v3=True)
    ops = {o["name"]: o for o in r.ops["operations"]}
    for p in r.auth["principals"]:
        tools = r.dep.tools(r.tok(p["id"]))
        assert {t.name for t in tools} == allowed_operations(r.auth, p["id"], list(ops)), p["id"]
        for t in tools:
            assert json.dumps(t.input_schema, sort_keys=True) == json.dumps(tool_schema(ops[t.name]), sort_keys=True)


def test_every_low_result_matches_its_frozen_form(rig):
    d, tk = rig.dep, rig.tok("researcher-2")
    sid = d.subscribe(tk, {"types": ["Threshold"]})
    check_low_result("subscribe", sid)
    rig.store.handle("seed").update("Threshold", "T-A", {"value": {"min": 5}})
    check_low_result("poll", d.poll(tk, sid.body["sub"]))
    for m, a in (("read_object", ("Hypothesis:H-A",)), ("read_object", ("Nope:1",)), ("list_objects", ("Rival",)),
                 ("list_objects", ("Zzz",)), ("list_links", ("Hypothesis:H-A", "HAS_RIVAL")), ("query", ("evidence_count", {"hypothesis": "H-C"})),
                 ("prov_decision", ("zz",)), ("prov_object", ("Hypothesis:H-A",)), ("authority_used_as", ("zz",))):
        check_low_result(m, getattr(d, m)(tk, *a))
    assert d.subscribe(tk, {"types": ["Nope"]}).status == "INVALID" and d.poll(tk, "sub-999").status == "INVALID"


# ---- determinism (s5): an A/A control --------------------------------------------------------------------------------------------
def test_aa_control_is_byte_identical(tmp_path):
    outs = []
    for _ in range(2):
        r = G3Rig(tmp_path, v3=True)
        sid = r.dep.subscribe(r.tok("researcher-2"), {"types": ["Threshold", "Evidence"]}).body["sub"]
        r.dep.direct(r.tok("researcher-1"), "attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C2"}, request_id="aa")
        outs.append(battery(r, "researcher-2", sid))
    assert outs[0] == outs[1]


# ---- low view rules ------------------------------------------------------------------------------------------------------------
def _view(r, who, objs, links=frozenset(), implied=frozenset()):
    obs = next(p for p in r.auth["principals"] if p["id"] == who)
    return low_view(effective_disclosure(r.auth, r.ops), obs, objs, set(links), set(implied))


def test_deny_overrides_allow_and_via_needs_a_visible_neighbour(rig):
    objs = {"Experiment:E1": {"id": "E1", "version": "1", "evaluator_ref": "x", "freeze_hash": "SECRET"},
            "Hypothesis:H1": {"id": "H1"}, "Evidence:V1": {"id": "V1", "payload_hash": "h", "git_commit": "SECRET2"}}
    v = _view(rig, "researcher-1", objs, {("PRODUCES", "Experiment:E1", "Evidence:V1")})
    assert v.objects["Experiment:E1"] == {"id": "E1", "version": "1", "evaluator_ref": "x"}      # deny rule removes freeze_hash
    assert v.objects["Evidence:V1"] == {"id": "V1", "payload_hash": "h"}                           # via a visible Experiment
    assert ("PRODUCES", "Experiment:E1", "Evidence:V1") in v.links
    v2 = _view(rig, "researcher-1", {k: x for k, x in objs.items() if k != "Experiment:E1"})
    assert "Evidence:V1" not in v2.objects                                                         # no visible neighbour, no via
    v3 = _view(rig, "viewer-1", objs, {("PRODUCES", "Experiment:E1", "Evidence:V1")})
    assert set(v3.objects) == {"Hypothesis:H1"} and v3.links == set()                              # public type only


def test_act_implies_exists_never_the_fields(rig):
    from paladin.sovview import implied_refs
    objs = {"Rival:R1": {"id": "R1", "statement": "S"}}
    obs = next(p for p in rig.auth["principals"] if p["id"] == "admin-1")
    imp = implied_refs(rig.ops, rig.auth, obs, {"Hypothesis:H1": {}, "Rival:R1": {}}, [])
    assert "Hypothesis:H1" in imp and "Rival:R1" not in imp                                      # no operation takes a Rival input
    v = _view(rig, "admin-1", {"Hypothesis:H1": {"id": "H1"}, "Experiment:E1": {"id": "E1", "freeze_hash": "S"}}, implied={"Experiment:E1"})
    assert v.objects["Experiment:E1"] == {}                                                       # existence only


# ---- hidden edges / parents (3.1) -------------------------------------------------------------------------------------------------
def test_hidden_parent_and_hidden_edge_are_answered_as_absent(tmp_path):
    r = G2Rig(tmp_path, auth=v2_mfg())
    assert r.delegate("planner-1", edge("e1", "planner-1", "ag-1")).status == "OK"
    assert r.delegate("ag-1", edge("e2", "ag-1", "ag-2", "e1")).status == "OK"
    sc = edge("n", "ag-3", "ag-4", "e1")
    assert r.delegate("ag-3", sc).body == r.delegate("ag-3", {**sc, "id": "n2", "parent": "nope"}).body == {"reason": "unknown_parent"}
    assert r.revoke("ag-3", "e1").body == r.revoke("ag-3", "nope").body == {"reason": "unknown_edge"}
    assert r.delegate("ag-2", edge("m", "ag-2", "ag-4", "e1")).body == {"reason": "not_parent_holder"}       # e1 is visible to ag-2 (below it)
    doc = r.dep.authority_state()
    assert capgraph.edge_visible(doc, "e1", "ag-2") and capgraph.edge_visible(doc, "e2", "planner-1")
    assert not capgraph.edge_visible(doc, "e1", "ag-3") and not capgraph.edge_visible(doc, "e2", "ag-3")
