"""G3 fix1 (H25-C, G3-E17): the review stage needs overturn >= k (PROT-H25 2.4), not the decision rule dissent > n-k."""
from r3_oracle import const_eval as C


def _doc(k, n):
    return {"bodies": [{"id": "b", "members": [f"m{i}" for i in range(n)], "rule": {"kind": "quorum", "k": k, "recuse": []}}]}


def _js(vals, stage):
    return [{"judge": f"m{i}", "value": v, "stage": stage, "seq": i, "tick": 0, "rid": f"r{i}"} for i, v in enumerate(vals)]


def test_review_one_overturn_of_k4_n4_is_awaiting():  # case-11-46
    assert C._body_result(_doc(4, 4), "b", "req", _js(["overturn"], "review"), "review") == C.AWAIT


def test_review_overturn_reaches_k():
    assert C._body_result(_doc(4, 4), "b", "req", _js(["overturn"] * 4, "review"), "review") == C.DENY
    assert C._body_result(_doc(2, 3), "b", "req", _js(["overturn"] * 2, "review"), "review") == C.DENY


def test_decision_stage_keeps_the_dissent_rule_known_positive():
    assert C._body_result(_doc(4, 4), "b", "req", _js(["dissent"], "decision"), "decision") == C.DENY


def test_ops_model_is_the_order_used_for_execute_and_act():  # G3-E17 confirmation
    import inspect
    from r3_oracle import const_judge
    assert "ops_model.evaluate" in inspect.getsource(const_judge)
