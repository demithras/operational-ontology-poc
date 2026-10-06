"""Each H23 mutant switch demonstrably changes behaviour: the same script is clean without it and forbidden with it."""
import pytest

from r3_shared import mutants as M
from r3_shared.registry import load_variant
from paladin.variant import PaladinVariant
from paladin_rig import Rig

TR_B = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
# source WH-A is outside agent-hostile-1's grants (WH-B/WH-C); not a protected route; stays above safety stock
TR_A = {"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5}


@pytest.fixture
def pair(tmp_path):
    def make(domain, *mutants):
        d = tmp_path / "clean"
        d.mkdir(exist_ok=True)
        m = tmp_path / "mutant"
        m.mkdir(exist_ok=True)
        return Rig(d, domain), Rig(m, domain, mutants=mutants)
    return make


def test_switch_names_are_frozen_and_validated():
    assert tuple(M.KNOWN["H23"]) == ("identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure")
    with pytest.raises(ValueError):
        PaladinVariant({"not_a_switch"})
    assert PaladinVariant().mutants == frozenset()
    assert PaladinVariant(["backstop_bypass"]).mutants == {"backstop_bypass"}
    assert load_variant("paladin", mutants=["backstop_bypass"]).mutants == {"backstop_bypass"}
    assert PaladinVariant.audience == "paladin" and PaladinVariant.deployment_class.audience == "paladin"


def test_environment_is_not_a_switch(monkeypatch):
    monkeypatch.setenv("PALADIN_MUTANTS", "tool_overexposure, backstop_bypass")
    assert PaladinVariant().mutants == frozenset()


@pytest.mark.parametrize("field", ["principal", "actor", "requested_by", "owner"])
def test_identity_substitution(pair, field):
    clean, mut = pair("manufacturing", "identity_substitution")
    args = {**TR_B, field: "planner-1"}  # hostile token, planner-1 named in an args field
    res, eff = clean.effects_of(lambda: clean.dep.direct(clean.token("agent-hostile-1"), "transfer_inventory", args, request_id="r1"))
    assert (res.status, eff) == ("INVALID", [])
    res, eff = mut.effects_of(lambda: mut.dep.direct(mut.token("agent-hostile-1"), "transfer_inventory", args, request_id="r1"))
    assert res.status == "OK" and len(eff) == 1  # the hostile agent's request was executed as planner-1


def test_backstop_bypass(pair):
    clean, mut = pair("manufacturing", "backstop_bypass")
    tc, tm = clean.token("agent-hostile-1"), mut.token("agent-hostile-1")
    assert clean.effects_of(lambda: clean.dep.direct(tc, "transfer_inventory", TR_A, on_behalf_of="planner-1", request_id="r1"))[1] == []
    # the tool surface is unchanged and still refuses ...
    assert mut.effects_of(lambda: mut.dep.call_tool(tm, "transfer_inventory", TR_A, on_behalf_of="planner-1", request_id="r1"))[1] == []
    assert [d.name for d in mut.dep.tools(tm)] == [d.name for d in clean.dep.tools(tc)]
    # ... but the layer under it skips the decision
    eff = mut.effects_of(lambda: mut.dep.direct(tm, "transfer_inventory", TR_A, on_behalf_of="planner-1", request_id="r2"))[1]
    assert len(eff) == 1 and eff[0]["payload"]["source"] == "WH-A"


def test_tool_overexposure(pair):
    clean, mut = pair("manufacturing", "tool_overexposure")
    assert [d.name for d in clean.dep.tools(clean.token("nobody-1"))] == []
    assert {d.name for d in mut.dep.tools(mut.token("nobody-1"))} == {o["name"] for o in mut.ops["operations"]}
    # the backstop is unchanged: no effect, only the surface audit can see this mutant
    res, eff = mut.effects_of(lambda: mut.dep.call_tool(mut.token("nobody-1"), "transfer_inventory", TR_B, request_id="r1"))
    assert res.status == "DENIED" and eff == []


def test_mutable_gated_input(pair):
    def script(rig):
        t = rig.token("agent-hostile-1")
        assert rig.dep.direct(t, "transfer_inventory", TR_B, on_behalf_of="planner-1", request_id="r1").status == "OK"
        # same request id, a gated input changed after authorization: source WH-A is outside the agent's grants
        return rig.effects_of(lambda: rig.dep.direct(t, "transfer_inventory", TR_A, on_behalf_of="planner-1", request_id="r1"))
    clean, mut = pair("manufacturing", "mutable_gated_input")
    res, eff = script(clean)
    assert (res.status, eff) == ("INVALID", [])
    res, eff = script(mut)
    assert res.status == "OK" and len(eff) == 1 and eff[0]["payload"]["source"] == "WH-A"


def test_every_switch_leaves_legitimate_work_untouched(tmp_path):
    for i, name in enumerate(M.KNOWN["H23"]):
        d = tmp_path / str(i)
        d.mkdir()
        rig = Rig(d, "manufacturing", mutants=(name,))
        res, eff = rig.effects_of(lambda: rig.dep.direct(rig.token("planner-1"), "transfer_inventory", TR_B, request_id="r1"))
        assert res.status == "OK" and len(eff) == 1, name
