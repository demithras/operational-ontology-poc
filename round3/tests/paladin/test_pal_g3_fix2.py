"""G3 fix2: G3-E17 post-authority order for mutating calls: deny rules -> target existence (E-6) -> preconditions -> approvals."""
from r3_shared.world import diff

TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 1}


def _send(r, args, rid):
    return r.dep.direct(r.token("planner-1"), "transfer_inventory", args, None, rid)


def test_e17_a_deny_rule_and_precondition_answer_denied(mfg):
    before = mfg.snap()
    res = _send(mfg, {**TRANSFER, "quantity": 10 ** 6}, "e17-a")
    assert res.status == "DENIED" and res.body["reason"] == "policy", (res.status, res.body)
    assert diff(before, mfg.snap()) == []


def test_e17_b_precondition_only_answers_invalid(mfg):
    before = mfg.snap()
    res = _send(mfg, {**TRANSFER, "quantity": 0}, "e17-b")
    assert res.status == "INVALID" and res.body["reason"] == "preconditions", (res.status, res.body)
    assert diff(before, mfg.snap()) == []


def test_e17_c_deny_rule_beats_nonexistent_target(mfg):
    before = mfg.snap()
    res = _send(mfg, {**TRANSFER, "part": "PX-NOPE", "quantity": 10 ** 6}, "e17-c")
    assert res.status == "DENIED" and res.body["reason"] == "policy", (res.status, res.body)
    assert diff(before, mfg.snap()) == []


def test_e17_nonexistent_target_without_a_deny_rule_is_still_not_found(proj):
    before = proj.snap()
    res = proj.dep.direct(proj.token("researcher-1"), "evaluate_hypothesis", {"hypothesis": "H-NOPE"}, None, "e17-d")
    assert (res.status, res.body) == ("INVALID", {"reason": "not_found"})
    assert diff(before, proj.snap()) == []
