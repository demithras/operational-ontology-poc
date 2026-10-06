"""PROT-H23-A8 for Paladin: R9 crash safety (both crash points), R5 after restart, R10 concurrency. Effects are measured
from the world store (WorldReader diff). Expected final states are written by hand."""
import threading
import time

import pytest

from paladin.core import Core
from r3_shared.authspec import load_auth_spec

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
BIG = {**TR, "quantity": 400}
PT = {"threshold": "T-A"}


def revoked_planner():
    spec = load_auth_spec("manufacturing")
    for p in spec["principals"]:
        if p["id"] == "planner-1":
            p["roles"], p["relations"] = [], []
    return spec


def mfg_call(rig, rid, args=TR, who="planner-1"):
    return rig.dep.direct(rig.token(who), "transfer_inventory", args, request_id=rid)


def proj_call(rig, rid, value=11):
    return rig.dep.direct(rig.token("researcher-1"), "edit_threshold", {**PT, "value": {"min": value}}, request_id=rid)


CASES = [("manufacturing", mfg_call, lambda i: {}), ("project", proj_call, lambda i: {"value": 11 + i})]


def call(rig, fn, rid, n=0):
    return fn(rig, rid) if rig.domain == "manufacturing" else fn(rig, rid, 11 + n)


@pytest.mark.parametrize("domain,fn,_", CASES)
def test_r9_before_commit_leaves_zero_effects_then_same_request_commits_once(make_rig, domain, fn, _):
    rig = make_rig(domain)
    rig.dep.arm_crash("before_commit")
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))
    assert (res.status, res.body["reason"], eff) == ("UNKNOWN", "crashed", [])
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))
    assert (res.status, res.body["reason"], eff) == ("UNAVAILABLE", "crashed", [])
    assert rig.dep.read(rig.token("viewer-1" if domain == "project" else "planner-1"), "get",
                        {"type": "Warehouse", "key": "WH-A"}).status == "UNAVAILABLE"
    rig.dep.restart()
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))  # nothing was committed: the same id is a first attempt
    assert res.status == "OK" and len(eff) == 1
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))
    assert res.status == "OK" and res.body.get("replayed") is True and eff == []


@pytest.mark.parametrize("domain,fn,_", CASES)
def test_r9_after_commit_has_exactly_the_request_effects_and_replay_adds_none(make_rig, domain, fn, _):
    rig = make_rig(domain)
    rig.dep.arm_crash("after_commit")
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))
    assert (res.status, res.body["reason"]) == ("UNKNOWN", "crashed") and len(eff) == 1
    assert call(rig, fn, "c1").status == "UNAVAILABLE"
    rig.dep.restart()
    res, eff = rig.effects_of(lambda: call(rig, fn, "c1"))  # same request_id after restart: never a second effect
    assert res.status == "OK" and eff == [], res
    res, eff = rig.effects_of(lambda: call(rig, fn, "c2", 1))  # a NEW id is a new request
    assert len(eff) == (1 if domain == "manufacturing" else 1)


def test_r9_new_request_id_after_crash_is_decided_against_current_authority(make_rig):
    rig = make_rig("manufacturing")
    rig.dep.arm_crash("after_commit")
    mfg_call(rig, "c1")
    rig.dep.restart()
    revoked = revoked_planner()
    rig.dep.set_authority(revoked)
    res, eff = rig.effects_of(lambda: mfg_call(rig, "c2"))
    assert res.status == "DENIED" and eff == []


def test_authority_in_force_survives_a_crash(make_rig):
    rig = make_rig("manufacturing")
    revoked = revoked_planner()
    rig.dep.set_authority(revoked)
    v = rig.dep.authority_version()
    rig.dep.crash()
    rig.dep.restart()
    assert rig.dep.authority_version() == v
    res, eff = rig.effects_of(lambda: mfg_call(rig, "c1"))
    assert res.status == "DENIED" and eff == []


def test_crash_between_requests_loses_nothing_committed(make_rig):
    rig = make_rig("manufacturing")
    assert mfg_call(rig, "c1").status == "OK"
    rig.dep.crash()
    rig.dep.restart()
    res, eff = rig.effects_of(lambda: mfg_call(rig, "c1"))
    assert res.status == "OK" and res.body["replayed"] is True and eff == []


def test_approval_is_single_use_across_a_crash_after_commit(make_rig):
    rig = make_rig("manufacturing")
    assert rig.dep.approve(rig.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
    rig.dep.arm_crash("after_commit")
    _, eff = rig.effects_of(lambda: mfg_call(rig, "c1", BIG))
    assert len(eff) == 1
    rig.dep.restart()
    res, eff = rig.effects_of(lambda: mfg_call(rig, "c2", BIG))  # the approval was consumed by the committed request
    assert (res.status, res.body["reason"], eff) == ("DENIED", "approval_required", [])


def test_approval_survives_a_crash_before_commit_and_stays_usable_once(make_rig):
    rig = make_rig("manufacturing")
    assert rig.dep.approve(rig.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
    rig.dep.arm_crash("before_commit")
    _, eff = rig.effects_of(lambda: mfg_call(rig, "c1", BIG))
    assert eff == []
    rig.dep.restart()
    assert mfg_call(rig, "c2", BIG).status == "OK"
    assert mfg_call(rig, "c3", BIG).status == "DENIED"


def test_armed_crash_is_taken_by_a_refused_request_too(make_rig):
    rig = make_rig("manufacturing")
    rig.dep.arm_crash("after_commit")
    res, eff = rig.effects_of(lambda: rig.dep.direct("garbage-token", "transfer_inventory", TR, request_id="c1"))
    assert (res.status, eff) == ("UNKNOWN", [])
    assert mfg_call(rig, "c2").status == "UNAVAILABLE"


# ---- R10 ---------------------------------------------------------------------------------------------------
def run_threads(n, fn):
    out, barrier = [None] * n, threading.Barrier(n)

    def work(i):
        barrier.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:  # noqa: BLE001 - an exception escaping a call is itself a failure the tests assert on
            out[i] = exc
    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


@pytest.mark.parametrize("domain,fn,_", CASES)
def test_r10_same_request_id_from_many_threads_commits_once(make_rig, domain, fn, _):
    rig = make_rig(domain)
    results, eff = [], None
    before = rig.snap()
    results = run_threads(10, lambda i: call(rig, fn, "same"))
    from r3_shared.world import diff
    eff = diff(before, rig.snap())
    assert len(eff) == 1, eff
    assert {r.status for r in results} <= {"OK", "UNAVAILABLE"} and any(r.status == "OK" for r in results)


def test_r10_one_approval_many_conflicting_requests_final_world_is_a_serial_outcome(make_rig):
    rig = make_rig("manufacturing")
    assert rig.dep.approve(rig.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
    before = rig.snap()
    results = run_threads(8, lambda i: mfg_call(rig, f"t{i}", BIG))
    from r3_shared.world import diff
    eff = diff(before, rig.snap())
    # any serial order: the first request consumes the single approval, the other seven are refused -> exactly one WMS command
    assert len(eff) == 1 and eff[0]["payload"]["quantity"] == 400
    assert sorted(r.status for r in results).count("OK") == 1


def test_r10_conflicting_state_transitions_final_world_is_a_serial_outcome(make_rig):
    rig = make_rig("project")
    tok = rig.token("researcher-1")
    before = rig.snap()
    results = run_threads(8, lambda i: rig.dep.direct(tok, "start_run", {"hypothesis": "H-B"}, request_id=f"s{i}"))
    from r3_shared.world import diff
    eff = diff(before, rig.snap())
    # serial: the first start_run moves H-B to RUNNING; later ones fail their precondition (or are unavailable)
    assert [(e["kind"], e["ref"]) for e in eff] == [("update", "Hypothesis:H-B")]
    assert eff[0]["changes"]["phase"][1] == "RUNNING"
    assert sum(r.status == "OK" for r in results) == 1


def test_r10_reads_and_tools_concurrent_with_writes_do_not_corrupt(make_rig):
    rig = make_rig("manufacturing")
    t = rig.token("planner-1")

    def f(i):
        if i % 3 == 0:
            return mfg_call(rig, f"w{i}")
        if i % 3 == 1:
            return rig.dep.read(t, "available_quantity", {"lot": "LOT-B-PX17"})
        return rig.dep.tools(t)
    run_threads(12, f)
    assert len([e for e in rig.snap()["effects"] if e["adapter"] == "WMS"]) == 4


# ---- the two new mutants -------------------------------------------------------------------------------------
def test_mutant_ledger_after_commit_volatile_double_commits_after_crash(make_rig, tmp_path):
    def script(rig):
        rig.dep.arm_crash("after_commit")
        mfg_call(rig, "c1")
        rig.dep.restart()
        return rig.effects_of(lambda: mfg_call(rig, "c1"))
    res, eff = script(make_rig("manufacturing"))
    assert res.body["replayed"] is True and eff == []
    d = tmp_path / "m"
    d.mkdir()
    from paladin_rig import Rig
    res, eff = script(Rig(d, "manufacturing", mutants=("ledger_after_commit_volatile",)))
    assert res.status == "OK" and len(eff) == 1  # a second effect for an already-committed request_id


def test_mutant_unsynchronized_commit_double_commits_same_request_id(make_rig, tmp_path, monkeypatch):
    real = Core.world_digest
    monkeypatch.setattr(Core, "world_digest", lambda self: (time.sleep(0.05), real(self))[1])  # widen the check -> commit window
    from paladin_rig import Rig
    from r3_shared.world import diff

    def clean(rig):  # the property: one effect set, no exception escaping a call
        before = rig.snap()
        out = run_threads(6, lambda i: mfg_call(rig, "same"))
        return len(diff(before, rig.snap())) == 1 and not any(isinstance(r, Exception) for r in out)
    assert clean(make_rig("manufacturing"))
    d = tmp_path / "m"
    d.mkdir()
    assert not clean(Rig(d, "manufacturing", mutants=("unsynchronized_commit",)))


def test_deploy_accepts_state_dir_and_ledger_lives_there(make_rig):
    import os
    rig = make_rig("manufacturing")
    assert mfg_call(rig, "c1").status == "OK"
    assert os.path.exists(os.path.join(rig.state_dir, "ledger.sqlite"))
