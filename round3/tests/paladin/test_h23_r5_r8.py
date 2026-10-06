"""H23 requirements R5-R8 (zero-effect negatives measured from the world store)."""
import copy

import pytest

from paladin.worldbridge import WorldExternalAdapter, WorldGitAdapter
from r3_shared.world import WorldConflict

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}


def zero(rig, fn):
    res, eff = rig.effects_of(fn)
    assert eff == [], f"unexpected world effects {eff} (result {res})"
    return res


# ---- R5 replay and idempotency --------------------------------------------------------------------------------
def test_r5_same_request_id_never_produces_a_second_effect(mfg):
    t = mfg.token("planner-1")
    first, eff = mfg.effects_of(lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1"))
    assert first.status == "OK" and len(eff) == 1
    for f in (mfg.dep.direct, mfg.dep.call_tool):
        again = zero(mfg, lambda: f(t, "transfer_inventory", TR, request_id="r1"))
        assert again.status == "OK" and again.body.get("replayed") is True
    assert len(mfg.snap()["effects"]) == 1


def test_r5_request_id_reuse_with_a_different_request_is_refused(mfg):
    t = mfg.token("planner-1")
    mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1")
    for args in ({**TR, "quantity": 61}, {**TR, "part": "PX-17"}):
        assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", args, request_id="r1")).status == "INVALID"
    other_op = zero(mfg, lambda: mfg.dep.direct(t, "reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55},
                                                request_id="r1"))
    assert other_op.status == "INVALID"
    # another subject reusing the id of a committed request
    assert zero(mfg, lambda: mfg.dep.direct(mfg.token("junior-1"), "transfer_inventory", TR, request_id="r1")).status == "INVALID"


def test_r5_missing_request_id_is_invalid(mfg):
    for rid in (None, "", 5):
        assert zero(mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", TR, request_id=rid)).status == "INVALID"


def test_r5_replay_after_set_authority_uses_the_authority_in_force_now(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1").status == "OK"
    v0 = mfg.dep.authority_version()
    revoked = copy.deepcopy(mfg.auth)
    revoked["grants"] = [g for g in revoked["grants"] if g["id"] != "transfer-inventory-planner"]
    assert mfg.dep.set_authority(revoked) is None
    v1 = mfg.dep.authority_version()
    assert v1 != v0 and len(v1) == 64
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1")).status == "DENIED"
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r2")).status == "DENIED"
    assert "transfer_inventory" not in [d.name for d in mfg.dep.tools(t)]
    mfg.dep.set_authority(mfg.auth)  # restore: the same committed request id must still never double-apply
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1")).body.get("replayed") is True


def test_r5_denied_request_id_may_be_retried_once_authorized(mfg):
    t = mfg.token("planner-1")
    revoked = copy.deepcopy(mfg.auth)
    revoked["grants"] = [g for g in revoked["grants"] if g["id"] != "transfer-inventory-planner"]
    mfg.dep.set_authority(revoked)
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1")).status == "DENIED"
    mfg.dep.set_authority(mfg.auth)
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1"))
    assert res.status == "OK" and len(eff) == 1


# ---- R6 commit-time preconditions ----------------------------------------------------------------------------------
def test_r6_preconditions_use_the_canonical_world_at_commit(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1").status == "OK"
    mfg.store.handle("seed").update("InventoryLot", "LOT-C-PX900", {"qualityStatus": "QUARANTINE"})  # world changes under us
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {**TR, "quantity": 61}, request_id="r2")).status == "DENIED"  # policy hard deny (quarantine)
    mfg.store.handle("seed").update("InventoryLot", "LOT-C-PX900", {"qualityStatus": "OK", "onHand": 10})
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {**TR, "quantity": 62}, request_id="r3")).status == "INVALID"


def test_r6_target_existence_and_stale_evidence(mfg, proj):
    t = mfg.token("planner-1")
    for args in ({**TR, "part": "PX-NOPE"}, {**TR, "source_warehouse": "WH-NOPE"}):
        assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", args, request_id=mfg.rid())).status == "INVALID"
    mfg.clock.advance(6)  # evidence snapshot was observed at tick 0: older than the 5-tick window
    assert zero(mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", TR, request_id="late")).status == "DENIED"  # stale-evidence policy
    assert zero(proj, lambda: proj.dep.direct(proj.token("researcher-1"), "start_run", {"hypothesis": "H-NOPE"},
                                              request_id="p1")).status == "INVALID"


def test_r6_project_lifecycle_is_checked_against_world_state(proj):
    t = proj.token("researcher-1")
    assert zero(proj, lambda: proj.dep.direct(t, "start_run", {"hypothesis": "H-A"}, request_id="p1")).status == "INVALID"  # DRAFT
    assert proj.dep.direct(t, "preregister_hypothesis", {"hypothesis": "H-A", "freeze_hash": "a" * 64}, request_id="p2").status == "OK"
    proj.store.handle("seed").update("Hypothesis", "H-A", {"phase": "EVALUATED"})  # moved on behind our back
    assert zero(proj, lambda: proj.dep.direct(t, "start_run", {"hypothesis": "H-A"}, request_id="p3")).status == "INVALID"


# ---- R7 explicit outcomes ------------------------------------------------------------------------------------------
def test_r7_denied_invalid_unavailable_are_distinct(mfg, monkeypatch):
    t = mfg.token("planner-1")
    denied = zero(mfg, lambda: mfg.dep.direct(mfg.token("nobody-1"), "transfer_inventory", TR, request_id="a"))
    invalid = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {**TR, "quantity": "ten"}, request_id="b"))
    invalid2 = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {"part": "PX-900"}, request_id="c"))

    def down(self, effect, payload):
        raise TimeoutError("WMS down")
    monkeypatch.setattr(WorldExternalAdapter, "apply", down)
    unavailable = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="d"))
    assert (denied.status, invalid.status, invalid2.status, unavailable.status) == ("DENIED", "INVALID", "INVALID", "UNAVAILABLE")
    monkeypatch.undo()
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="d"))
    assert res.status == "OK" and len(eff) == 1  # an UNAVAILABLE request id was never consumed


def test_r7_error_midway_commits_no_partial_effect(proj, monkeypatch):
    real, calls = WorldGitAdapter.apply, {"n": 0}

    def flaky(self, effect, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("git backend vanished")
        return real(self, effect, payload)
    monkeypatch.setattr(WorldGitAdapter, "apply", flaky)
    args = {"experiment": "E-C@v1", "contract_version": "CV-1"}  # three canonical effects: the second one fails
    res = zero(proj, lambda: proj.dep.direct(proj.token("researcher-1"), "new_experiment_version", args, request_id="p1"))
    assert res.status == "UNAVAILABLE"
    monkeypatch.undo()
    res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token("researcher-1"), "new_experiment_version", args, request_id="p1"))
    assert res.status == "OK" and len(eff) == 3


@pytest.mark.parametrize("bad", [{"claim": 7}, {"claim": ""}, {}, {"claim": "ok", "extra": 1}, {"claim": "ephemeral: scratch"}])
def test_r7_project_invalid_inputs_have_no_effect(proj, bad):
    assert zero(proj, lambda: proj.dep.direct(proj.token("researcher-1"), "create_hypothesis", bad, request_id="p1")).status in ("INVALID", "DENIED")


# ---- R8 legitimate progress ----------------------------------------------------------------------------------------
def test_r8_authorized_requests_commit_including_delegated_and_admin(mfg, proj):
    cases = [("planner-1", None, TR), ("junior-1", None, {**TR, "quantity": 5}), ("agent-1", "planner-1", TR),
             ("admin-1", None, TR)]
    for who, obo, args in cases:
        res, eff = mfg.effects_of(lambda: mfg.dep.direct(mfg.token(who), "transfer_inventory", args, on_behalf_of=obo,
                                                         request_id=mfg.rid()))
        assert res.status == "OK" and len(eff) == 1, (who, res)
    for who, op, args in (("researcher-2", "create_hypothesis", {"claim": "r2 claim"}), ("admin-1", "flag_orphan_component",
                          {"component": "cmp-orphan"}), ("agent-evidence-1", "start_run", {"hypothesis": "H-B"}),
                          ("agent-draft-1", "create_hypothesis", {"claim": "draft agent"})):
        res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token(who), op, args, request_id=proj.rid()))
        assert res.status == "OK" and eff, (who, op, res)


def test_malformed_calls_have_no_effect(mfg):
    t = mfg.token("planner-1")
    for args in (None, [], "x", 5, {"quantity": object()}):
        for f in (mfg.dep.direct, mfg.dep.call_tool):
            assert zero(mfg, lambda: f(t, "transfer_inventory", args, request_id=mfg.rid())).status == "INVALID"
    assert zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, on_behalf_of=["planner-1"], request_id="x")).status == "DENIED"
