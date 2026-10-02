"""Capability semantics: hand-written truth cases, the Hypothesis differential (surface == oracle), and the live-Engine cross-check."""
import pytest
from hypothesis import given, settings

from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack as mfg_pack
from domains.project.pack import build_pack as prj_pack
from eoo_h21 import cases, differential, engine_check, opaque

REL = lambda t, k, r: [t, k, r]  # noqa: E731


def case(pid, roles=(), rels=(), delegated_by=None, objs=None, registered=True, flags=None):
    return {"principal": {"pid": pid, "roles": list(roles), "relations": [list(r) for r in rels], "delegated_by": delegated_by},
            "registered": registered, "world": {"objects": objs, "flags": flags or {"preregistered": [], "fault": False}}}


def both(ir, surf, c):
    got = differential.surface_sets(surf, ir, c, opaque.make(ir))
    want = differential.load_oracle_module("authority_oracle").Reference(ir).sets(c)
    assert got == want
    return got


def mfg_world(**over):
    objs = {o["id"]: [] for o in load_ir("manufacturing")["object_types"]}
    objs.update({"Warehouse": ["W1", "W2"], "Part": ["P1"]})
    objs.update(over)
    return objs


def granted(sets, action):
    return [a for a in sets["actionable"] if a.startswith(action + "|")]


def test_relation_rule_needs_the_relation_on_every_bound_warehouse(built):
    ir, _d, _i, _sdk, _c, surf = built["manufacturing"]
    full = both(ir, surf, case("a", rels=[REL("Warehouse", "W1", "planner"), REL("Warehouse", "W2", "planner")], objs=mfg_world()))
    part = both(ir, surf, case("a", rels=[REL("Warehouse", "W1", "planner")], objs=mfg_world()))
    assert len(granted(full, "transfer_inventory")) == 4  # (W1|W2) x (W1|W2), part fixed
    assert granted(part, "transfer_inventory") == ['transfer_inventory|{"destination_warehouse":"W1","part":"P1","source_warehouse":"W1"}']
    assert "act_transfer_inventory" in full["tools"] and "act_expedite_purchase_order" not in full["tools"]  # no allow rule matches that capability


def test_delegation_needs_the_rule_flag_and_an_allowed_delegator(built):
    ir, _d, _i, _sdk, _c, surf = built["manufacturing"]
    objs, W = mfg_world(), [REL("Warehouse", "W1", "planner"), REL("Warehouse", "W2", "planner")]
    agent = [REL("Warehouse", "W1", "agent_grant"), REL("Warehouse", "W2", "agent_grant")]
    planner = {"pid": "p", "roles": [], "relations": W, "delegated_by": None}
    assert granted(both(ir, surf, case("agent", rels=agent, delegated_by=planner, objs=objs)), "transfer_inventory")  # flag set, delegator allowed
    nobody = {"pid": "n", "roles": [], "relations": [], "delegated_by": None}
    assert not granted(both(ir, surf, case("agent", rels=agent, delegated_by=nobody, objs=objs)), "transfer_inventory")
    delegated_planner = case("d", rels=W, delegated_by=planner, objs=objs)  # planner rule has no delegation flag
    assert not granted(both(ir, surf, delegated_planner), "transfer_inventory")


def test_unregistered_principal_and_selector_fault_expose_nothing(built):
    ir, _d, _i, _sdk, _c, surf = built["project"]
    objs = {o["id"]: [f"{o['id']}-0"] for o in ir["object_types"]}
    ok = both(ir, surf, case("r", roles=["researcher"], objs=objs))
    assert len(ok["actionable"]) == 10 and len(ok["tools"]) > 60
    ghost = both(ir, surf, case("r", roles=["researcher"], objs=objs, registered=False))
    assert ghost["tools"] == [] and ghost["queryable"] == []
    fault = both(ir, surf, case("r", roles=["researcher"], objs=objs, flags={"preregistered": [], "fault": True}))
    names = {a.split("|")[0] for a in fault["actionable"]}  # a failing opaque selector (ProjectOntology:*) fails closed; grammar selectors still work
    assert "edit_threshold" not in names and "start_run" not in names and "create_hypothesis" in names and fault["queryable"] != []
    assert both(ir, surf, case("v", roles=["viewer"], objs=objs))["actionable"] == []


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
@settings(max_examples=60, deadline=None, database=None)
@given(data=__import__("hypothesis").strategies.data())
def test_surface_equals_oracle_on_generated_cases(built, dom, data):
    ir, _d, _i, _sdk, _c, surf = built[dom]
    c = data.draw(cases.case_strategy(ir))
    both(ir, surf, c)


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
def test_unique_cases_cover_every_capability_path(built, dom):
    ir, _d, _i, _sdk, _c, surf = built[dom]
    cs = cases.unique_cases(ir, 1000, 5)
    assert len({cases.case_sha(c) for c in cs}) == 1000
    r = differential.run(ir, surf, cs)
    cov = r["coverage"]
    assert r["mismatching_cases"] == 0 and cov["delegated"] > 200 and cov["with_allowed_action"] > 100 and cov["registered"] < 1000
    assert cov["selector_fault_world"] > 0
    # manufacturing has a delegable rule (agent_grant); the project contract has none, so a delegate is never granted there
    assert (cov["delegated_with_allowed_action"] > 0) == (dom == "manufacturing")


def test_differential_known_negative_a_tampered_surface_is_caught(built):
    ir, _d, _i, _sdk, _c, surf = built["project"]
    cs = cases.unique_cases(ir, 200, 6)
    real = surf.AgentSurface.capabilities

    def leaky(self):
        out = real(self)
        out["actionable"] = out["actionable"] + ['create_hypothesis|{"claim":"x"}']  # an overexposed capability
        return out
    surf.AgentSurface.capabilities = leaky
    try:
        r = differential.run(ir, surf, cs)
    finally:
        surf.AgentSurface.capabilities = real
    assert r["mismatching_cases"] > 0 and r["overexposed_total"] > 0 and differential.run(ir, surf, cs)["mismatching_cases"] == 0


@pytest.mark.parametrize("dom,pack", [("manufacturing", mfg_pack), ("project", prj_pack)])
def test_surface_oracle_and_live_engine_agree(built, dom, pack):
    ir, _d, _i, _sdk, _c, surf = built[dom]
    r = engine_check.run(boot(dom, pack()), ir, surf, 150, 4)
    assert r["disagreements"] == 0 and r["decisions_compared"] > 1000 and r["engine_allowed_total"] > 0
