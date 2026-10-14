"""G5-E35 B1 (R29-11 + G5-E16): redelivery of a request_id returns the RECORDED decision (status, and reason for non-OK),
with zero new world rows and zero new anchor entries; also under a narrowed/widened authority and after a restart."""
import pytest

from conv_g5_util import TRANSFER, V0, make_g5, narrowed, stop_all
from r3_shared.authsvc import doc_digest


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True)
    yield r
    stop_all()


def sync(rig, doc):
    """Publish a version and make the service adopt it (lease fetch happens in the next governed call)."""
    rig.actl.publish(doc)
    rig.tick(5)   # lease (4 ticks) expired: the next call fetches the new version


def rows(rig):
    return len(rig.reader.log())


def head(rig):
    h = rig.anchor.head(rig.dep.service.stream)
    return None if h is None else h["seq"]


def snapshot(rig):
    return rows(rig), head(rig)


def probe_narrowed_denies(rig):
    r = rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 11}, "probe-new")
    assert (r.status, r.body.get("reason")) == ("DENIED", "no_matching_allow")


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("via", ["direct", "call_tool"])
def test_committed_ok_redelivered_under_narrowed_version_returns_ok(rig, restart, via):
    def call(rid):
        t = rig.token("planner-1")
        return rig.dep.direct(t, "transfer_inventory", TRANSFER, None, rid) if via == "direct" \
            else rig.dep.call_tool(t, "transfer_inventory", TRANSFER, None, rid)
    rig.fresh()
    first = call("r1")
    assert first.status == "OK"
    sync(rig, narrowed())
    probe_narrowed_denies(rig)            # the narrowed version really denies this principal/operation now
    if restart:
        rig.restart()
    before = snapshot(rig)
    again = call("r1")
    assert again.status == "OK" and again.body.get("replayed") is True
    assert snapshot(rig) == before
    assert rig.commits().count("r1") == 1


def test_denied_redelivered_after_widened_version_returns_the_original_denied(rig):
    sync(rig, narrowed())
    first = rig.d("planner-1", "transfer_inventory", TRANSFER, "d1")
    assert (first.status, first.body["reason"]) == ("DENIED", "no_matching_allow")
    sync(rig, V0)
    assert rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 9}, "d-new").status == "OK"   # widened: new id passes
    before = snapshot(rig)
    for _ in range(2):
        again = rig.d("planner-1", "transfer_inventory", TRANSFER, "d1", fresh=False)
        assert (again.status, again.body["reason"]) == ("DENIED", "no_matching_allow")
        assert snapshot(rig) == before
    rig.restart()
    again = rig.d("planner-1", "transfer_inventory", TRANSFER, "d1", fresh=False)
    assert (again.status, again.body["reason"]) == ("DENIED", "no_matching_allow")
    assert snapshot(rig) == before
    assert "d1" not in rig.commits()


def test_other_subject_or_args_reusing_a_denied_id_is_not_answered_from_the_record(rig):
    sync(rig, narrowed())
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "d2").status == "DENIED"
    sync(rig, V0)
    assert rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 7}, "d2").status == "OK"


def test_tampered_idempotency_record_is_non_ok_with_zero_effect(rig):
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "t1").status == "OK"
    sync(rig, narrowed())
    probe_narrowed_denies(rig)   # the version is adopted (its authority mark written) before the snapshot
    from conventional.histledger import rid_key
    rig.dep.service.history.put(rid_key("t1"), b"{not json")
    before = snapshot(rig)
    for via in ("direct", "call_tool"):
        t = rig.token("planner-1")
        r = rig.dep.direct(t, "transfer_inventory", TRANSFER, None, "t1") if via == "direct" \
            else rig.dep.call_tool(t, "transfer_inventory", TRANSFER, None, "t1")
        assert r.status != "OK"
    assert snapshot(rig) == before
    assert rig.commits().count("t1") == 1


def test_missing_idempotency_record_is_non_ok_with_zero_effect(rig):
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "t2").status == "OK"
    sync(rig, narrowed())
    probe_narrowed_denies(rig)   # the version is adopted (its authority mark written) before the snapshot
    from conventional.histledger import rid_key
    rig.dep.service.history._con.execute("DELETE FROM hist WHERE key=?", (rid_key("t2"),))
    before = snapshot(rig)
    r = rig.d("planner-1", "transfer_inventory", TRANSFER, "t2", fresh=False)
    assert r.status != "OK"
    assert snapshot(rig) == before
