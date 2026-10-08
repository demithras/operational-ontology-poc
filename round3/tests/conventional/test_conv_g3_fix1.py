"""G3 fix1: G3-E17 post-authority order (deny rules -> existence -> preconditions -> approvals)."""
from conv_helpers import diff

TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 1}


def _send(r, args, rid):
    return r.dep.direct(r.token("planner-1"), "transfer_inventory", args, None, rid)


def test_e17_deny_rule_beats_precondition_and_existence(mfg):
    before = mfg.snap()
    both = _send(mfg, {**TRANSFER, "quantity": 10 ** 6}, "e17-a")  # deny rule (safety stock) AND a failing precondition
    assert both.status == "DENIED" and both.body["reason"] == "business_rule"
    only_pre = _send(mfg, {**TRANSFER, "quantity": 0}, "e17-b")
    assert only_pre.status == "INVALID" and only_pre.body["reason"] == "precondition_failed"
    assert diff(before, mfg.snap()) == []
