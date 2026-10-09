"""R28-1 decide-before-dispatch, R28-2 no adapter-minted authority, R28-3 generic enforcement, seam adoption (C28-1)."""
import pytest

from conv_g4_util import (BIG_EXPEDITE, EXPEDITE, TRANSFER, Dup, FalseFailure, FalseSuccess, Honest, Omit, PolicyReply, TargetSubst,
                          TimeoutAfterApply, make_g4)
from r3_shared.world import diff

ADAPTERS = [Honest, FalseSuccess, FalseFailure, TimeoutAfterApply, Omit, TargetSubst, Dup, PolicyReply]


def _decision(res):
    return (res.status, {k: v for k, v in res.body.items() if k != "outcomes"})


@pytest.mark.parametrize("cls", ADAPTERS, ids=lambda c: c.adapter_id)
def test_r28_1_decision_identical_whatever_the_adapter_does(tmp_path, cls):
    """Twin differential: status, body (minus outcomes) and canonical world diff equal the honest twin's."""
    out = {}
    for name, adapter in (("twin", Honest), ("byz", cls)):
        r = make_g4(tmp_path / name, default=adapter)
        before = r.snap()
        res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="rq")
        out[name] = (_decision(res), diff(before, r.snap()))
    assert out["twin"][0][0] == "OK"
    assert out["byz"] == out["twin"]


def test_c28_1_no_legacy_external_write_with_binding(tmp_path):
    r = make_g4(tmp_path)
    before = r.snap()
    assert r.dep.call_tool(r.token("planner-1"), "transfer_inventory", TRANSFER, request_id="t1").status == "OK"
    d = diff(before, r.snap())
    assert not [e for e in d if e["kind"] == "external"], "an in-transaction external_write ran"
    assert r.store.handle("t").external_effects() == []
    assert len(r.sent("WMS")) == 1 and len(r.ledger()) == 1


def test_c28_1_legacy_path_unchanged_without_binding(mfg):
    before = mfg.snap()
    assert mfg.dep.call_tool(mfg.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="l1").status == "OK"
    assert any(e["kind"] == "external" for e in diff(before, mfg.snap()))
    assert mfg.dep.dispatch_pending().body == {"submitted": 0}
    assert "outcomes" not in mfg.dep.call_tool(mfg.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="l2").body


def test_r28_2_policy_shaped_reply_is_an_outcome_not_a_decision(tmp_path):
    r = make_g4(tmp_path, default=PolicyReply)
    res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="g1")
    assert res.status == "OK"                                   # the adapter's "deny" changed nothing
    r.ctl.advance(r.clock.now() + 20)                           # G4-E8: the server tick must reach the watermark
    assert [o["state"] for o in r.dep.reconcile("g1", r.clock.now() + 20).body["outcomes"]] == ["RECONCILED_FAILED"]


def test_r28_2_reply_approval_does_not_satisfy_a_later_approval_rule(tmp_path):
    r = make_g4(tmp_path, default=PolicyReply)
    assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="g2").status == "OK"
    before = r.snap()
    res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", BIG_EXPEDITE, request_id="g3")
    assert (res.status, res.body["reason"]) == ("DENIED", "approval_required")
    assert diff(before, r.snap()) == [] and len(r.sent("ERP")) == 1   # zero effects, zero further submits


def test_r28_3_approval_rule_enforced_in_decision_plane_zero_effects(tmp_path):
    r = make_g4(tmp_path)
    before = r.snap()
    res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", BIG_EXPEDITE, request_id="a1")
    assert (res.status, res.body["reason"]) == ("DENIED", "approval_required")
    assert diff(before, r.snap()) == [] and r.sent("ERP") == [] and r.ledger() == []


def test_r28_3_approved_request_commits_and_dispatches_once(tmp_path):
    r = make_g4(tmp_path)
    assert r.dep.approve(r.token("admin-1"), "expedite_purchase_order", BIG_EXPEDITE, "planner-1").status == "OK"
    assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", BIG_EXPEDITE, request_id="a2").status == "OK"
    assert len(r.sent("ERP")) == 1 and len(r.ledger()) == 1


def test_r28_3_project_overlay_public_publish_needs_approval(tmp_path):
    r = make_g4(tmp_path, "project")
    args = {"verdict": "verdict-H-D-1", "visibility": "public"}
    res = r.dep.call_tool(r.token("researcher-1"), "publish_result", args, request_id="p1")
    assert (res.status, res.body.get("reason")) == ("DENIED", "approval_required") and r.sent("REGISTRY") == []
