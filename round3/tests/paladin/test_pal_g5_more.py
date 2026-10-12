"""PROT-H29 R29-5(b), R29-6 (outcome plane), R29-12 progress, crash points CP6-CP8, restricted resume (P1g-7), legacy path unchanged."""
import pytest

from g5_rig import DEP, EXP, RES, TR, G5Rig, narrowed
from r3_shared.extobs import ObserverFault
from r3_shared.host import HostDead
from r3_shared.recovery import validate_recovery_view

from test_pal_g5_recovery import ledger_rows


def states(dep, rid, wm):
    return [o["state"] for o in dep.reconcile(rid, wm).body["outcomes"]]


def test_outcome_plane_adapter_outage_is_pending_unknown_not_failed_and_recovers_after_heal():
    r = G5Rig()
    try:
        r.tick()
        r.ctl.outage("ERP", DEP, 1, 4)                                          # EXT:ERP down for the first part of the 8-tick window
        assert r.call("planner-1", "expedite_purchase_order", EXP, "x1").status == "OK"   # decision plane SAFE
        assert r.dep.dispatch_pending().body == {"submitted": 0}                # refused: nothing applied, nothing learnt
        assert ledger_rows(r) == [] and r.dep.dependency_status()["EXT:ERP"] == "DOWN"
        assert states(r.dep, "x1", r.clock.now()) in (["PENDING"], ["UNKNOWN"])  # never RECONCILED_FAILED while the system was down inside E
        r.tick(3)                                                               # t=4: healed, still inside the window (E = 1 + 8)
        assert r.dep.dispatch_pending().body == {"submitted": 1}
        assert [x[0] for x in ledger_rows(r)] == ["x1#0"]
        r.tick(10)
        assert states(r.dep, "x1", r.clock.now()) == ["RECONCILED_SUCCESS"]
        assert r.dep.dispatch_pending().body == {"submitted": 0} and len(ledger_rows(r)) == 1   # R28-7: no duplicate effect
    finally:
        r.finish()


def test_outcome_plane_observer_loss_is_never_reported_as_failure():
    r = G5Rig()
    try:
        r.dep = r.deploy()
        assert r.call("planner-1", "transfer_inventory", TR, "y1").status == "OK"
        r.dep.dispatch_pending()
        c = r.dep._c
        c.ext.b = type(c.ext.b)(c.ext.b.systems, c.ext.b.adapters, c.ext.b.root_caps, r.external_binding(ObserverFault("unavailable")).observer, c.ext.b.window)
        r.tick(20)                                                              # far past the expiry: only a SEEN absence may be a failure
        assert states(r.dep, "y1", r.clock.now() + 1) == ["UNKNOWN"]            # rule U: observer unavailable
        assert r.dep.dependency_status()["OBS"] == "DOWN"
    finally:
        r.finish()


def test_r29_12_safe_requests_progress_under_unrelated_faults_and_after_recovery():
    r = G5Rig()
    try:
        tok = r.token("planner-1")
        r.ctl.outage("ERP", DEP, 0, 9)
        r.actl.outage(DEP, 2, 4, "drop")                                        # a lease window: t=2,3 are SAFE (lease granted at 1 runs to 5)
        eligible = ok = 0
        for rid, op, args in (("z1", "transfer_inventory", TR), ("z2", "reschedule_work_order", RES)):
            eligible += 1
            ok += r.call("planner-1", op, args, rid).status == "OK"
            r.tick()
        for rid, op, args in (("z3", "transfer_inventory", {**TR, "quantity": 2}), ("z4", "reschedule_work_order", RES)):
            eligible += 1                                                       # t=2,3 with AUTH down inside the lease window
            ok += r.call("planner-1", op, args, rid).status == "OK"
            r.tick()
        eligible += 1
        ok += r.dep.read(tok, "list", {"type": "Part"}).status == "OK"          # t=4: AUTH down, lease granted at 3 runs to 7
        assert (ok, eligible) == (5, 5)
        assert sorted(c for c in r.commits() if c.startswith("z")) == ["z1", "z2", "z3", "z4"]   # each committed exactly once
    finally:
        r.finish()


def test_r29_12_negative_a_variant_that_refuses_everything_during_a_fault_scores_below_the_floor():
    r = G5Rig(mutants=("global_halt_on_fault",))
    try:
        r.ctl.outage("ERP", DEP, 0, 9)
        r.call("planner-1", "expedite_purchase_order", EXP, "h1")
        r.dep.dispatch_pending()                                                # trips the EXT:ERP breaker
        ok = sum(r.call("planner-1", "transfer_inventory", {**TR, "quantity": q}, f"h{q}").status == "OK" for q in (2, 3, 4))
        assert ok / 3 < 0.95
    finally:
        r.finish()


@pytest.fixture
def host_rig():
    r = G5Rig(inproc=False)
    yield r
    r.finish()


def test_cp6_idle_kill_between_calls_resume_keeps_the_committed_set(host_rig):
    r = host_rig
    px = r.host()
    px.arm("CP6_idle", "i1")
    assert px.direct(r.token("planner-1"), "transfer_inventory", TR, None, "i1").status == "OK"   # the reply left; the host dies right after
    px.wait_dead()
    px2 = r.host(resume=True)
    assert [c["request_id"] for c in validate_recovery_view(px2.recovery_view())["committed"]] == r.commits() == ["i1"]
    again = px2.direct(r.token("planner-1"), "transfer_inventory", TR, None, "i1")
    assert again.status == "OK" and again.body.get("replayed") is True and r.commits() == ["i1"]


def test_cp7_kill_after_observer_read_loses_only_the_unapplied_snapshot(host_rig):
    r = host_rig
    px = r.host()
    assert px.direct(r.token("planner-1"), "transfer_inventory", TR, None, "o1").status == "OK"
    px.dispatch_pending()
    r.tick(12, px)
    px.arm("CP7_reconcile_after_read", "o1")
    with pytest.raises(HostDead):
        px.reconcile("o1", r.clock.now() + 1)
    px2 = r.host(resume=True, tick=r.clock.now())
    assert [i["state"] for i in px2.recovery_view()["intents"]] in (["PENDING"], ["UNKNOWN"])   # admissible: the snapshot was not durable
    assert px2.reconcile("o1", r.clock.now() + 1).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"   # re-read gives the same fact
    assert len(ledger_rows(r)) == 1


def test_cp8_kill_during_recovery_then_a_second_resume_converges(host_rig):
    r = host_rig
    px = r.host()
    px.arm("CP1_before_commit", "w1")
    with pytest.raises(HostDead):
        px.direct(r.token("planner-1"), "transfer_inventory", TR, None, "w1")
    px2 = r.host(resume=True)
    assert px2.direct(r.token("planner-1"), "expedite_purchase_order", EXP, None, "w2").status == "OK"
    px2.kill()
    px3 = r.host(resume=True)                                                   # resume #2 over the same stores
    px3.arm("CP8_during_recovery", "dispatch_pending")
    with pytest.raises(HostDead):
        px3.dispatch_pending()                                                  # the first dispatch after a resume dies
    px4 = r.host(resume=True)
    assert px4.dispatch_pending().body["submitted"] == 1 and [x[0] for x in ledger_rows(r)] == ["w2#0"]
    assert [c["request_id"] for c in px4.recovery_view()["committed"]] == r.commits() == ["w2"]


def test_resume_is_restricted_no_anchor_append_no_lease_no_external_write_no_observer_read(host_rig):
    r = host_rig
    px = r.host()
    assert px.direct(r.token("planner-1"), "transfer_inventory", TR, None, "p1").status == "OK"
    px.kill()
    stream = None
    import sqlite3
    con = sqlite3.connect(str(r.root / "hist.db"))
    stream = con.execute("SELECT value FROM hist WHERE key='meta/stream'").fetchone()[0].decode()
    con.close()
    head, leases, fl = r.anchor.client().head(stream), len(r.actl.log()["leases"]), r.ctl.fault_log()
    px2 = r.host(resume=True)
    validate_recovery_view(px2.recovery_view())
    assert r.anchor.client().head(stream) == head and len(r.actl.log()["leases"]) == leases and r.ctl.fault_log() == fl
    assert ledger_rows(r) == []                                                 # nothing written to ExternalWorld by the rebuild


def test_approve_is_a_governed_mutation_anchor_down_blocks_it_with_zero_effects():
    r = G5Rig()
    try:
        r.nctl.partition(r.dep._c.prov.stream, 1, 4, "drop")
        r.tick()
        res = r.dep.approve(r.token("supervisor-1"), "expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 900}, "planner-1")
        assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "ANCHOR"})
        assert r.dep.recovery_view()["approvals_open"] == []
        r.tick(4)
        assert r.dep.approve(r.token("supervisor-1"), "expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 900}, "planner-1").status == "OK"
        assert len(r.dep.recovery_view()["approvals_open"]) == 1               # unconsumed approval is part of the canonical state
    finally:
        r.finish()


def test_legacy_path_without_authority_source_is_unchanged():
    r = G5Rig()
    try:
        dep = r.deploy(with_auth=False)
        assert dep._h29 is False and dep.dependency_status() == {}
        res = dep.direct(r.token("planner-1"), "transfer_inventory", TR, request_id="l1")
        assert res.status == "OK" and not r.actl.log()["leases"]                # no lease was ever fetched
        assert dep.authority_version() == dep._c.version()                      # stamp == the digest of the document in force (H24)
        dep2 = r.deploy(with_auth=False, resume=True)                            # legacy resume (restart semantics) works too
        assert dep2.direct(r.token("planner-1"), "transfer_inventory", TR, request_id="l1").body.get("replayed") is True
    finally:
        r.finish()


@pytest.mark.parametrize("cp,effect_lands_before_kill", [("CP4_adapter_before_apply", False), ("CP5_adapter_after_apply", True)])
def test_cp4_cp5_kill_around_the_adapter_write_never_duplicates_the_effect(host_rig, cp, effect_lands_before_kill):
    r = host_rig
    r.adapter_factory = "g5_adapters:build_cp"                                  # the frozen harness wrapper's role: crash points around the write
    px = r.host()
    assert px.direct(r.token("planner-1"), "transfer_inventory", TR, None, "a1").status == "OK"
    px.arm(cp, "a1#0")
    with pytest.raises(HostDead):
        px.dispatch_pending()
    assert [x[0] for x in ledger_rows(r)] == (["a1#0"] if effect_lands_before_kill else [])
    px2 = r.host(resume=True)
    assert [i["state"] for i in px2.recovery_view()["intents"]] in (["PENDING"], ["UNKNOWN"])   # RC1: nothing observed yet
    px2.dispatch_pending()                                                      # the SAME cap is presented again; the cap bounds applied rows
    r.tick(12, px2)
    assert [o["state"] for o in px2.reconcile("a1", r.clock.now() + 1).body["outcomes"]] == ["RECONCILED_SUCCESS"]
    assert [x[0] for x in ledger_rows(r)] == ["a1#0"]                           # exactly one effect, whichever side of the write the host died on


def test_every_crash_point_is_exercised_by_a_paladin_g5_test():
    import pathlib
    from r3_shared.faultplane import CRASH_POINTS
    text = "".join(p.read_text() for p in pathlib.Path(__file__).parent.glob("test_pal_g5_*.py") if p.name != pathlib.Path(__file__).name) + \
        pathlib.Path(__file__).read_text().split("def test_every_crash_point")[0]
    missing = [c for c in CRASH_POINTS if c not in text and c.split("_")[0] + "_" not in text]
    assert missing == []                                                        # set difference over CP1..CP8
    assert all(c in text for c in CRASH_POINTS)
