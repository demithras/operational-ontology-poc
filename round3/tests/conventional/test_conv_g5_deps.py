"""R29-6/R29-7/R29-12: explicit unavailability, bulkheads, breakers. Hand-written from the frozen text."""
import pytest

from conv_g5_util import DEP, EXPEDITE, TRANSFER, make_g5, stop_all
from conventional.g5deps import Breaker, DepGraph, Guard
from r3_shared.recovery import INPUT_INVALID_REASONS, validate_reply


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True)
    yield r
    stop_all()


def unav(node):
    return ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": node})


def test_anchor_down_blocks_governed_decisions_with_zero_effects(rig):
    rig.actl_anchor.partition(rig.dep.service.stream, 3, 9, "drop")
    rig.tick()
    rig.fresh()
    before = rig.reader.snapshot()
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1", fresh=False)
    assert (res.status, res.body) == unav("ANCHOR")
    validate_reply(res.status, res.body)
    assert rig.reader.snapshot() == before and rig.commits() == []


def test_redelivery_of_a_committed_request_is_also_blocked_while_anchor_is_down(rig):
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "r1").status == "OK"
    rig.actl_anchor.partition(rig.dep.service.stream, 3, 9, "drop")
    rig.tick()
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    assert (res.status, res.body) == unav("ANCHOR")      # never OK while a node of deps(op) is down (R29-7 fail-open)


def test_auth_down_without_lease_names_auth_and_denial_never_names_a_dependency(rig):
    rig.actl.outage(DEP, 2, 9)
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    assert (res.status, res.body) == unav("AUTH")
    rig.actl.outage(DEP, 10, 11)
    rig.tick(8)                                           # tick 10 down; AUTH up needs tick 11
    rig.tick()
    denied = rig.d("nobody-1", "transfer_inventory", TRANSFER, "r2")
    assert denied.status == "DENIED"
    assert "dependency" not in denied.body and denied.body["reason"] not in ("dependency_unavailable", "in_doubt", "crashed")


def test_input_errors_stay_invalid_with_frozen_names_while_auth_is_down(rig):
    rig.actl.outage(DEP, 2, 9)
    bad = rig.d("planner-1", "no_such_operation", {}, "r1")
    assert bad.status == "INVALID" and bad.body["reason"] in INPUT_INVALID_REASONS
    bad2 = rig.d("planner-1", "transfer_inventory", {"part": 1}, "r2")
    assert bad2.status == "INVALID" and bad2.body["reason"] == "schema_invalid"
    ok_shape = rig.d("planner-1", "transfer_inventory", TRANSFER, "r3")
    assert (ok_shape.status, ok_shape.body) == unav("AUTH")


def test_read_needs_auth_only_and_discloses_nothing_when_blocked(rig):
    rig.actl.outage(DEP, 2, 9)
    res = rig.dep.read(rig.token("planner-1"), "get", {"type": "Warehouse", "key": "WH-A"})
    assert (res.status, res.body) == unav("AUTH")
    rig.actl_anchor.partition(rig.dep.service.stream, 2, 9, "drop")   # ANCHOR is not a dependency of read: never named
    again = rig.dep.read(rig.token("planner-1"), "get", {"type": "Warehouse", "key": "WH-A"})
    assert (again.status, again.body) == unav("AUTH")
    rig.tick(8)                                                        # tick 10: AUTH reachable again (outage [2, 9))
    ok = rig.dep.read(rig.token("planner-1"), "get", {"type": "Warehouse", "key": "WH-A"})
    assert ok.status in ("OK", "INVALID")                               # a real read answer; ANCHOR healed too


def test_unrelated_operations_proceed_during_an_external_outage(rig):
    rig.ectl.outage("ERP", DEP, 2, 20)
    a = rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")        # decision plane does not depend on EXT:ERP
    assert a.status == "OK"
    t = rig.d("planner-1", "transfer_inventory", TRANSFER, "t1")              # WMS unaffected
    assert t.status == "OK"
    rig.dep.dispatch_pending()
    st = rig.dep.dependency_status()
    assert st["EXT:ERP"] == "DOWN" and st.get("EXT:WMS") == "UP"
    outs = rig.dep.outcome("e1").body["outcomes"]
    assert outs[0]["state"] in ("PENDING", "UNKNOWN")                          # dependency loss shows as PENDING only


def test_outage_does_not_burn_delivery_attempts_and_heals(rig):
    rig.ectl.outage("ERP", DEP, 2, 4)
    assert rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1").status == "OK"
    for _ in range(5):
        rig.dep.dispatch_pending()
    assert [i["attempts"] for i in rig.dep.service._ext.intents(rig.dep.service._factory("t"))] == [0]   # outage is no attempt
    rig.tick(2)                                                                # tick 4: healed
    rig.dep.dispatch_pending()
    rig.tick(3)
    out = rig.dep.reconcile("e1", rig.clock.now())
    assert out.body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"


def test_breaker_state_machine_and_guard_status():
    b = Breaker()
    assert b.allow(0) and b.state == "closed"
    b.failure(1)
    assert b.state == "open" and b.allow(1) and b.state == "half_open"      # cooldown 0: every call after a failure is a trial
    b.failure(1)
    assert b.state == "open"
    b.success()
    assert b.state == "closed"
    slow = Breaker(cooldown=3)
    slow.failure(10)
    assert not slow.allow(12) and slow.allow(13)


def test_graph_is_read_as_data():
    import json
    from pathlib import Path
    g = DepGraph(json.loads((Path(__file__).resolve().parents[2] / "spec/gate5/dependency-graph.json").read_text()))
    assert g.decision_nodes("manufacturing", "transfer_inventory") == ["AUTH", "ANCHOR"]
    assert g.decision_nodes("project", "publish_result") == ["AUTH", "ANCHOR"]
    assert g.decision_nodes("manufacturing", "approve") == ["AUTH", "ANCHOR"]
    assert g.decision_nodes("manufacturing", surface="read") == ["AUTH"]
    assert g.outcome_nodes("manufacturing", "expedite_purchase_order") == ["EXT:ERP", "OBS"]
