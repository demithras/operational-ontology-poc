"""R29-8: hard restart. Every crash is a SIGKILL of a spawned variant host at a shared crash point; resume is a NEW process
(deploy(resume=True)) over the surviving stores. Hand-written expectations from PROT-H29 and PROTOCOL-P1g."""
import pytest

from conv_g5_util import DEP, EXPEDITE, TRANSFER, make_g5, stop_all
from r3_shared.host import HostDead
from r3_shared.recovery import validate_recovery_view


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True, deploy=False)
    yield r
    stop_all()


def killed_call(rig, point, key, op="transfer_inventory", args=TRANSFER, rid="r1"):
    px = rig.host()
    px.advance(rig.clock.now())
    px.arm(point, key)
    with pytest.raises(HostDead):
        px.direct(rig.token("planner-1"), op, args, None, rid)
    px.wait_dead()
    return px


def resumed(rig):
    px = rig.host(resume=True)
    px.advance(rig.clock.now())
    return px


def test_cp1_before_commit_leaves_nothing_and_redelivery_commits_once(rig):
    killed_call(rig, "CP1_before_commit", "r1")
    assert rig.commits() == []
    px = resumed(rig)
    assert validate_recovery_view(px.recovery_view())["committed"] == []
    assert px.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1").status == "OK"
    assert rig.commits() == ["r1"]


def test_cp2_after_commit_unanchored_is_completed_on_redelivery(rig):
    killed_call(rig, "CP2_after_commit", "r1")
    assert rig.commits() == ["r1"]
    px = resumed(rig)
    v = validate_recovery_view(px.recovery_view())
    assert [c["request_id"] for c in v["committed"]] == ["r1"] and v["authority"] == {"version": None, "lease_until": None}
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1")
    assert again.status == "OK" and again.body["replayed"] is True
    assert rig.commits() == ["r1"]                                   # no duplicate commit
    assert px.replay("r1").status == "VERIFIED"                       # the anchor entry now exists and the envelope verifies


def test_cp3_after_anchor_append_is_repaired_without_a_second_anchor_entry(rig):
    killed_call(rig, "CP3_after_anchor_append", "r1")
    px = resumed(rig)
    assert px.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1").body["replayed"] is True
    assert px.replay("r1").status == "VERIFIED"
    assert rig.commits() == ["r1"]


def test_cp6_idle_kill_between_calls_loses_nothing(rig):
    px = rig.host()
    px.advance(rig.clock.now())
    px.arm("CP6_idle", "r1")
    px.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1")   # reply goes out, then the host dies
    px.wait_dead()
    px2 = resumed(rig)
    assert [c["request_id"] for c in px2.recovery_view()["committed"]] == ["r1"]
    assert px2.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1").body["replayed"] is True


def test_cp8_crash_during_recovery_then_second_resume_delivers_exactly_once(rig):
    rig.ectl.outage("ERP", DEP, 2, 4)
    px = rig.host()
    px.advance(rig.clock.now())
    px.direct(rig.token("planner-1"), "expedite_purchase_order", EXPEDITE, None, "e1")
    px.kill()
    px2 = resumed(rig)
    rig.tick(2)
    px2.advance(rig.clock.now())
    px2.arm("CP8_during_recovery", "dispatch_pending")
    with pytest.raises(HostDead):
        px2.dispatch_pending()
    px2.wait_dead()
    px3 = resumed(rig)
    px3.advance(rig.clock.now())
    px3.dispatch_pending()
    rig.tick(3)
    px3.advance(rig.clock.now())
    out = px3.reconcile("e1", rig.clock.now())
    assert out.body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"
    import sqlite3
    con = sqlite3.connect(f"file:{rig.tmp / 'ext' / 'external.db'}?mode=ro", uri=True)
    assert con.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1


def test_process_cache_cannot_survive_a_kill_and_no_lease_is_trusted_after_it(rig):
    px = rig.host()
    px.advance(rig.clock.now())
    px.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1")
    assert px.recovery_view()["authority"]["version"] is not None
    px.kill()
    rig.actl.outage(DEP, rig.clock.now(), rig.clock.now() + 5)               # AUTH down at resume: no lease, no progress
    px2 = resumed(rig)
    assert px2.recovery_view()["authority"] == {"version": None, "lease_until": None}
    res = px2.direct(rig.token("planner-1"), "transfer_inventory", {**TRANSFER, "quantity": 1}, None, "r2")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
