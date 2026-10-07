"""P10: an approval binds on_behalf_of LITERALLY (null != explicit delegator); effects measured from the world store."""
import pytest

BIG = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 100}
FORMS = [(None, "planner-1"), ("planner-1", None)]


def _approve(rig, who, obo):
    assert rig.dep.approve(rig.token("senior-1"), "transfer_inventory", BIG, who, on_behalf_of=obo).status == "OK"


def _commit(rig, who, obo, rid):
    return rig.effects_of(lambda: rig.dep.direct(rig.token(who), "transfer_inventory", BIG, on_behalf_of=obo, request_id=rid))


@pytest.mark.parametrize("who", ["agent-1", "agent-hostile-1"])
@pytest.mark.parametrize("a_obo,c_obo", FORMS)
def test_mismatched_form_is_denied_with_zero_effects(mfg, who, a_obo, c_obo):
    _approve(mfg, who, a_obo)
    res, eff = _commit(mfg, who, c_obo, "m1")
    assert res.status == "DENIED" and res.body["reason"] == "approval_required" and eff == []
    # the unconsumed approval still serves the exact form it was given for
    res, eff = _commit(mfg, who, a_obo, "m2")
    assert res.status == "OK" and len(eff) == 1


@pytest.mark.parametrize("who", ["agent-1", "agent-hostile-1"])
@pytest.mark.parametrize("obo", [None, "planner-1"])
def test_same_form_commits_once_and_consumes(mfg, who, obo):
    _approve(mfg, who, obo)
    res, eff = _commit(mfg, who, obo, "s1")
    assert res.status == "OK" and len(eff) == 1
    res, eff = _commit(mfg, who, obo, "s2")
    assert res.status == "DENIED" and res.body["reason"] == "approval_required" and eff == []


@pytest.mark.parametrize("a_obo,c_obo", FORMS)
def test_binding_holds_across_crash_restart(mfg, a_obo, c_obo):
    _approve(mfg, "agent-1", a_obo)
    mfg.dep.crash()
    mfg.dep.restart()
    res, eff = _commit(mfg, "agent-1", c_obo, "c1")
    assert res.status == "DENIED" and res.body["reason"] == "approval_required" and eff == []
    res, eff = _commit(mfg, "agent-1", a_obo, "c2")
    assert res.status == "OK" and len(eff) == 1
    res, eff = _commit(mfg, "agent-1", a_obo, "c3")
    assert res.status == "DENIED" and eff == []
