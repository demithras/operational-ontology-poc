"""G5-E35 B1 (redelivery returns the RECORDED decision under any later authority version, restart or not, zero new rows) and
B2 (inline dispatch of external effects at commit; dispatch_pending then submits nothing for them)."""
import sqlite3

import pytest

from g5_rig import RES, TR, G5Rig, narrowed


@pytest.fixture
def rig():
    r = G5Rig()
    yield r
    r.finish()


def ext_rows(rig):
    con = sqlite3.connect(f"file:{rig.root / 'ext' / 'external.db'}?mode=ro", uri=True)
    try:
        return con.execute("SELECT correlation FROM effects ORDER BY seq").fetchall()
    finally:
        con.close()


def narrow_in_force(rig):
    rig.actl.publish(narrowed(rig.auth0))
    rig.tick(4)


def test_b1_committed_ok_redelivered_after_a_narrowing_returns_the_original_ok_without_rows(rig):
    first = rig.call("planner-1", "transfer_inventory", TR, "b1")
    assert first.status == "OK"
    commits, rows = rig.commits(), ext_rows(rig)
    narrow_in_force(rig)
    assert rig.call("planner-1", "transfer_inventory", {**TR, "quantity": 7}, "b1x").status == "DENIED"   # the narrowing is in force
    again = rig.call("planner-1", "transfer_inventory", TR, "b1")
    assert again.status == "OK" and again.body.get("replayed") is True
    assert rig.commits() == commits and ext_rows(rig) == rows


def test_b1_same_after_a_restart(rig):
    assert rig.call("planner-1", "transfer_inventory", TR, "b2").status == "OK"
    commits, rows = rig.commits(), ext_rows(rig)
    narrow_in_force(rig)
    dep2 = rig.deploy(resume=True)                                                               # a new deployment over the surviving stores
    again = rig.call("planner-1", "transfer_inventory", TR, "b2", dep=dep2)
    assert again.status == "OK"
    assert rig.commits() == commits and ext_rows(rig) == rows


def test_b1_negative_a_different_request_under_a_used_id_is_still_refused(rig):
    assert rig.call("planner-1", "transfer_inventory", TR, "b3").status == "OK"
    narrow_in_force(rig)
    res = rig.call("planner-1", "transfer_inventory", {**TR, "quantity": 9}, "b3")
    assert res.status != "OK" and rig.commits().count("b3") == 1


def test_b1_denied_redelivered_after_a_widening_returns_the_original_denial(rig):
    rig.actl.publish(narrowed(rig.auth0, "reschedule_work_order"))
    rig.tick(4)
    first = rig.call("planner-1", "reschedule_work_order", RES, "b4")
    assert first.status == "DENIED"
    rig.actl.publish(narrowed(rig.auth0, "transfer_inventory"))                                  # widened for reschedule
    rig.tick(5)
    assert rig.call("planner-1", "reschedule_work_order", {**RES, "new_planned_start": 56}, "b4x").status == "OK"   # the widening is in force
    commits = rig.commits()
    again = rig.call("planner-1", "reschedule_work_order", RES, "b4")
    assert (again.status, again.body) == (first.status, first.body)
    dep2 = rig.deploy(resume=True)
    again2 = rig.call("planner-1", "reschedule_work_order", RES, "b4", dep=dep2)
    assert (again2.status, again2.body) == (first.status, first.body)
    assert rig.commits() == commits and "b4" not in commits


def test_b1_tampered_idempotency_record_is_non_ok_with_zero_effect(rig):
    assert rig.call("planner-1", "transfer_inventory", TR, "b5").status == "OK"
    commits, rows = rig.commits(), ext_rows(rig)
    con = sqlite3.connect(str(rig.root / "hist.db"))
    n = con.execute("DELETE FROM hist WHERE key='led/req/b5'").rowcount
    con.commit(), con.close()
    assert n == 1
    dep2 = rig.deploy(resume=True)
    res = rig.call("planner-1", "transfer_inventory", TR, "b5", dep=dep2)
    assert res.status != "OK"
    assert rig.commits() == commits and ext_rows(rig) == rows


def test_b2_external_effects_are_dispatched_inline_at_commit_and_dispatch_pending_adds_none(rig):
    assert rig.call("planner-1", "transfer_inventory", TR, "d1").status == "OK"
    assert [r[0] for r in ext_rows(rig)].count("d1#0") == 1                                       # applied before any dispatch_pending
    res = rig.dep.dispatch_pending()
    assert res.status == "OK" and res.body == {"submitted": 0}
    assert [r[0] for r in ext_rows(rig)].count("d1#0") == 1


def test_b2_no_inline_dispatch_while_the_system_is_down_the_outbox_retries_later(rig):
    from g5_rig import DEP
    for s in rig.systems["systems"]:
        rig.ctl.outage(s, DEP, 0, 3)
    assert rig.call("planner-1", "transfer_inventory", TR, "d2").status == "OK"
    assert ext_rows(rig) == []
    rig.tick(3)
    assert rig.dep.dispatch_pending().body["submitted"] >= 1
    assert [r[0] for r in ext_rows(rig)].count("d2#0") == 1
