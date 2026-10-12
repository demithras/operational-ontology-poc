"""R29-12 bulkheads (unrelated operations proceed per node), R29-3 no fail-open disclosure, R29-4 tamper, the agent tool surface."""
import pytest

from conv_g5_util import DEP, EXPEDITE, TRANSFER, make_g5, stop_all
from r3_shared.histstore import TamperView


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True)
    yield r
    stop_all()


def test_auth_outage_leaves_replay_and_explain_unblocked(rig):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    rig.actl.outage(DEP, 2, 30)
    assert rig.dep.replay("r1").status == "VERIFIED" and rig.dep.explain("r1").status == "VERIFIED"   # deps: ANCHOR only


def test_anchor_outage_leaves_reads_unblocked(rig):
    rig.actl_anchor.partition(rig.dep.service.stream, 2, 30, "drop")
    res = rig.dep.read(rig.token("planner-1"), "get", {"type": "Warehouse", "key": "WH-A"})
    assert res.status != "UNAVAILABLE"                       # read depends on AUTH only
    assert rig.dep.replay("x").status == "UNRESOLVED"        # replay does depend on ANCHOR: an honest non-verification


def test_observer_outage_never_blocks_decisions_and_shows_as_pending(rig):
    from r3_shared.extobs import ObserverFault
    rig.binding.observer.fault = ObserverFault("unavailable")
    assert rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1").status == "OK"
    out = rig.dep.reconcile("e1", rig.clock.now())
    assert out.status == "OK" and out.body["outcomes"][0]["state"] in ("PENDING", "UNKNOWN")   # P1f-6 rule U, never RECONCILED_FAILED
    assert rig.dep.dependency_status()["OBS"] == "DOWN"


def test_tool_surface_is_gated_like_direct_and_bad_token_is_not_a_denial_while_blocked(rig):
    rig.actl.outage(DEP, 2, 30)
    res = rig.dep.call_tool(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, "r1")
    assert (res.status, res.body["dependency"]) == ("UNAVAILABLE", "AUTH")
    bad = rig.dep.call_tool("not-a-token", "transfer_inventory", TRANSFER, None, "r2")
    assert (bad.status, bad.body["dependency"]) == ("UNAVAILABLE", "AUTH")                    # R29-7: DENIED would be a misclassification
    unknown = rig.dep.call_tool(rig.token("planner-1"), "no_such_tool", {}, None, "r3")
    assert (unknown.status, unknown.body["reason"]) == ("INVALID", "unknown_tool")


def test_tampered_idempotency_record_is_never_trusted_after_resume(rig):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    tv = TamperView(rig.tmp / "hist.db")
    rid_keys = tv.keys("ledger/")
    assert rid_keys, "the ledger record must exist in the HistoryStore"
    tv.delete(rid_keys[0])
    rig.restart()
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1", fresh=False)
    assert res.status != "OK" and rig.commits() == ["r1"]    # zero new effects, no consumption of the damaged record


def test_unhashable_or_unknown_operation_names_never_break_the_gate(rig):
    rig.actl.outage(DEP, 2, 30)
    for bad in (["x"], {"a": 1}, None, 7):
        res = rig.dep.direct(rig.token("planner-1"), bad, {}, None, "rx")
        assert res.status == "INVALID" and res.body["reason"] == "unknown_operation"
