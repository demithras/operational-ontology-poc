"""R9 crash safety (PROT-H23-A8): both armed crash points, replay after restart, authority durability, the volatile-ledger mutant."""
import pytest

from conv_helpers import VALID
from r3_shared.world import diff

TRANSFER = {**VALID["transfer_inventory"], "destination_warehouse": "WH-C"}  # unprotected route: external effect only
SUPERSEDE = VALID["supersede_hypothesis"]  # canonical effect, single-shot (phase EVALUATED -> SUPERSEDED)


def _send(rig, rid="c1", who="planner-1", op="transfer_inventory", args=TRANSFER):
    return rig.dep.direct(rig.token(who), op, args, request_id=rid)


def test_before_commit_crash_leaves_zero_effects_and_blocks_until_restart(mfg):
    before = mfg.snap()
    mfg.dep.arm_crash("before_commit")
    r = _send(mfg)
    assert (r.status, r.body["reason"]) == ("UNKNOWN", "crashed")
    assert diff(before, mfg.snap()) == []
    for res in (_send(mfg, "c2"), mfg.dep.call_tool(mfg.token("planner-1"), "transfer_inventory", TRANSFER, request_id="c3"),
                mfg.dep.read(mfg.token("planner-1"), "get", {"type": "Warehouse", "key": "WH-A"})):
        assert (res.status, res.body["reason"]) == ("UNAVAILABLE", "crashed")
    assert mfg.dep.tools(mfg.token("planner-1")) == []
    assert diff(before, mfg.snap()) == []
    mfg.dep.restart()
    assert _send(mfg).status == "OK"  # the same request_id never committed: it commits now, exactly once
    assert len(diff(before, mfg.snap())) == 1
    assert _send(mfg).body.get("replayed") is True and len(diff(before, mfg.snap())) == 1


def test_after_commit_crash_has_exactly_the_requests_effects_and_replay_adds_none(mfg):
    before = mfg.snap()
    mfg.dep.arm_crash("after_commit")
    r = _send(mfg)
    assert (r.status, r.body["reason"]) == ("UNKNOWN", "crashed")
    assert len(diff(before, mfg.snap())) == 1
    assert _send(mfg, "c9").status == "UNAVAILABLE"
    mfg.dep.restart()
    r = _send(mfg)  # same request_id after restart: durable ledger answers, no second effect
    assert r.status == "OK" and r.body.get("replayed") is True
    assert len(diff(before, mfg.snap())) == 1


def test_after_commit_crash_then_new_request_id_is_a_new_request_against_current_state(proj):
    before = proj.snap()
    proj.dep.arm_crash("after_commit")
    assert _send(proj, "p1", "researcher-1", "supersede_hypothesis", SUPERSEDE).status == "UNKNOWN"
    committed = diff(before, proj.snap())
    assert len(committed) == 2  # phase update + SUPERSEDED_BY link
    proj.dep.restart()
    again = _send(proj, "p1", "researcher-1", "supersede_hypothesis", SUPERSEDE)
    assert again.status == "OK" and again.body.get("replayed") is True
    fresh = _send(proj, "p2", "researcher-1", "supersede_hypothesis", SUPERSEDE)  # new id: the lifecycle deny rule now fires (G3-E17: rules precede preconditions)
    assert fresh.status == "DENIED"
    assert diff(before, proj.snap()) == committed


def test_before_commit_crash_then_new_request_id_commits_once(proj):
    before = proj.snap()
    proj.dep.arm_crash("before_commit")
    assert _send(proj, "p1", "researcher-1", "supersede_hypothesis", SUPERSEDE).status == "UNKNOWN"
    assert diff(before, proj.snap()) == []
    proj.dep.restart()
    assert _send(proj, "p9", "researcher-1", "supersede_hypothesis", SUPERSEDE).status == "OK"
    assert len(diff(before, proj.snap())) == 2


def test_crash_between_requests_loses_nothing_durable(mfg):
    before = mfg.snap()
    assert _send(mfg).status == "OK"
    mfg.dep.crash()
    assert _send(mfg, "c2").status == "UNAVAILABLE"
    mfg.dep.restart()
    assert _send(mfg).body.get("replayed") is True and len(diff(before, mfg.snap())) == 1


def test_authority_in_force_survives_crash_and_restart(mfg):
    mfg.dep.set_authority({**mfg.auth, "grants": [g for g in mfg.auth["grants"] if g["id"] != "transfer-inventory-planner"]})
    ver = mfg.dep.authority_version()
    assert _send(mfg, "a1").status == "DENIED"
    mfg.dep.crash()
    mfg.dep.restart()
    assert mfg.dep.authority_version() == ver  # not reverted to the deploy-time spec
    before = mfg.snap()
    assert _send(mfg, "a2").status == "DENIED" and diff(before, mfg.snap()) == []


def test_crash_during_approval_registration(mfg):
    args = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 100}
    h = mfg.store.handle("seed")
    h.update("InventoryLot", "LOT-B-PX17", {"onHand": 400})  # so safety stock does not bind
    h.close()
    mfg.dep.arm_crash("before_commit")
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", args, "planner-1").status == "UNKNOWN"
    mfg.dep.restart()
    assert _send(mfg, "big", args=args).body["reason"] == "approval_required"  # nothing was registered
    mfg.dep.arm_crash("after_commit")
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", args, "planner-1").status == "UNKNOWN"
    mfg.dep.restart()
    assert _send(mfg, "big", args=args).status == "OK"  # the registered approval is durable and still single-use
    assert _send(mfg, "big2", args=args).body["reason"] == "approval_required"


def test_arm_survives_refused_requests_and_rejects_bad_points(mfg):
    with pytest.raises(ValueError):
        mfg.dep.arm_crash("during_commit")
    mfg.dep.arm_crash("before_commit")
    assert _send(mfg, "d1", who="nobody-1").status == "DENIED"  # never reaches the commit point: no crash
    assert _send(mfg, "d2").status == "UNKNOWN"


def test_mutant_ledger_after_commit_volatile_double_commits_on_replay(make):
    counts = {}
    for switches in ([], ["ledger_after_commit_volatile"]):
        rig = make("manufacturing", switches)
        before = rig.snap()
        rig.dep.arm_crash("after_commit")
        assert _send(rig).status == "UNKNOWN"
        rig.dep.restart()
        _send(rig)
        counts[bool(switches)] = len(diff(before, rig.snap()))
    assert counts == {False: 1, True: 2}


def test_mutant_without_crash_still_replays_so_only_the_crash_path_is_weakened(make):
    rig = make("manufacturing", ["ledger_after_commit_volatile"])
    before = rig.snap()
    assert _send(rig).status == "OK" and _send(rig).body.get("replayed") is True
    assert len(diff(before, rig.snap())) == 1
