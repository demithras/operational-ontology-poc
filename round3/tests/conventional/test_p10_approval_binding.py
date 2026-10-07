"""P10: an approval binds on_behalf_of LITERALLY (null vs explicit delegator are different requests)."""
import pytest

from conv_helpers import zero_effects
from r3_shared.world import diff

ARGS = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 100}
DELEGATES = ["agent-1", "agent-hostile-1"]


def _approve(rig, agent, obo):
    r = rig.dep.approve(rig.token("senior-1"), "transfer_inventory", ARGS, agent, obo)
    assert r.status == "OK", (r.status, r.body)


def _commit(rig, agent, obo, rid):
    return rig.dep.direct(rig.token(agent), "transfer_inventory", dict(ARGS), obo, rid)


@pytest.mark.parametrize("agent", DELEGATES)
@pytest.mark.parametrize("approve_obo,commit_obo", [(None, "planner-1"), ("planner-1", None)])
def test_mismatched_on_behalf_of_is_denied_with_zero_effects(mfg, agent, approve_obo, commit_obo):
    _approve(mfg, agent, approve_obo)
    with zero_effects(mfg):
        r = _commit(mfg, agent, commit_obo, "r1")
        assert (r.status, r.body.get("reason")) == ("DENIED", "approval_required")


@pytest.mark.parametrize("agent", DELEGATES)
@pytest.mark.parametrize("obo", [None, "planner-1"])
def test_same_form_commits_once_and_consumes(mfg, agent, obo):
    _approve(mfg, agent, obo)
    before = mfg.snap()
    assert _commit(mfg, agent, obo, "r1").status == "OK"
    assert diff(before, mfg.snap()) != []
    with zero_effects(mfg):
        r = _commit(mfg, agent, obo, "r2")
        assert (r.status, r.body.get("reason")) == ("DENIED", "approval_required")


@pytest.mark.parametrize("approve_obo,commit_obo", [(None, "planner-1"), ("planner-1", None)])
def test_binding_survives_crash_restart(mfg, approve_obo, commit_obo):
    _approve(mfg, "agent-1", approve_obo)
    mfg.dep.crash()
    mfg.dep.restart()
    with zero_effects(mfg):
        assert _commit(mfg, "agent-1", commit_obo, "r1").body.get("reason") == "approval_required"
    assert _commit(mfg, "agent-1", approve_obo, "r2").status == "OK"
