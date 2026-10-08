"""G3 fix5: (1) PROT-H25 s2.2 / G3-E14(3) each precedence criterion applies to the SURVIVING candidate set only
(specialis must not compare against bodies an earlier criterion removed); (2) compliance checks for G3-E25..E27."""
import pytest

from conv_g3_util import make_g3
from conventional.govproc import Procedure

WO = lambda keys: {"operations": ["reschedule_work_order"], "resources": [{"type": "WorkOrder", "keys": keys}]}  # noqa: E731


def body(i, rank):
    return {"id": i, "rank": rank, "members": ["supervisor-1"], "rule": {"kind": "single"}}


def matter(i, who, keys):
    return {"id": i, "competent": [who], "concurrence": False, "scope": WO(keys), "on_absent": "await",
            "review": {"by": who, "window": 3}}


def proc(precedence, bodies, matters, superior=()):
    return Procedure({"bodies": bodies, "matters": matters, "superior": list(superior), "precedence": precedence})


RES = [("WorkOrder", "WO-42")]
OP = "reschedule_work_order"


def narrow_broad():
    # m-narrow (office-lead, rank 1) is strictly narrower than m-broad (office-mid, rank 2)
    return ([body("office-lead", 1), body("office-mid", 2)],
            [matter("m-narrow", "office-lead", ["WO-42"]), matter("m-broad", "office-mid", None)])


def test_specialis_ignores_candidates_eliminated_by_rank_573_shape():
    b, m = narrow_broad()
    r = proc(["rank", "specialis"], b, m).route(OP, RES)
    assert not isinstance(r, str) and r.bodies == ("office-mid",)  # surviving body decides -> routed, not unresolved


def test_specialis_alone_still_prefers_the_narrower_matter():
    b, m = narrow_broad()
    r = proc(["specialis"], b, m).route(OP, RES)
    assert not isinstance(r, str) and r.bodies == ("office-lead",)


def test_specialis_after_superior_740_shape():
    b, m = narrow_broad()
    r = proc(["superior", "specialis"], b, m, superior=[["office-lead", "office-mid"]]).route(OP, RES)
    assert not isinstance(r, str) and r.bodies == ("office-mid",)  # office-mid is superior; narrower matter's body is gone


def test_specialis_then_rank_order_matters():
    b, m = narrow_broad()
    r = proc(["specialis", "rank"], b, m).route(OP, RES)
    assert not isinstance(r, str) and r.bodies == ("office-lead",)


def test_specialis_two_survivors_still_unresolved_when_no_narrower_survivor():
    b = [body("a", 1), body("b", 1)]
    m = [matter("m1", "a", None), matter("m2", "b", None)]
    assert proc(["rank", "specialis"], b, m).route(OP, RES) == "precedence_unresolved"


# ---- G3-E25..E27 ------------------------------------------------------------------------------------------------
A = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}


@pytest.fixture
def r(tmp_path):
    rig = make_g3(tmp_path, "hierarchical", governance=None, history=True)
    yield rig
    rig.anchor_proc.proc.kill()


def test_e25_own_decision_args_true_and_effect_digest_marker_kind_is_digest(r):
    r.dep.direct(r.token("planner-1"), "transfer_inventory", A, None, "tx1")
    res = r.dep.prov_decision(r.token("planner-1"), "tx1")
    assert res.body["decision"]["args_digest"] not in ({"redacted": "args"}, {"redacted": "digest"})  # own: true value
    assert res.body["decision"]["effect_digest"] == {"redacted": "digest"}  # G3-E25: digest kind, not "effect_digest"


def test_e27_reply_reason_equals_decision_reason(r):
    ok = r.dep.direct(r.token("planner-1"), "transfer_inventory", A, None, "tx1")
    bad = r.dep.direct(r.token("planner-1"), "transfer_inventory", dict(A, quantity=-1), None, "rf2")
    for rid, rep in (("tx1", ok), ("rf2", bad)):
        d = r.dep.prov_decision(r.token("planner-1"), rid).body["decision"]
        assert d["reason"] == (rep.body.get("reason") or "ok") and d["status"] == rep.status


def test_e27_authority_used_as_on_own_refused_request_answers_with_empty_path(r):
    bad = r.dep.direct(r.token("planner-1"), "transfer_inventory", dict(A, quantity=-1), None, "rf2")
    assert bad.status == "INVALID"
    d = r.dep.prov_decision(r.token("planner-1"), "rf2")
    u = r.dep.authority_used_as(r.token("planner-1"), "rf2")
    assert (d.status, u.status) == ("OK", "OK")
    assert u.body["path"] == [] and u.body["authority_version"] == {"redacted": "digest"}
    assert u.body["world_seq"] == d.body["decision"]["world_seq"] and u.body["tick"] == d.body["decision"]["tick"]


def test_e27_refused_request_is_invisible_to_others_and_matches_unknown(r):
    r.dep.direct(r.token("planner-1"), "transfer_inventory", dict(A, quantity=-1), None, "rf2")
    other = r.dep.authority_used_as(r.token("nobody-1"), "rf2")
    ghost = r.dep.authority_used_as(r.token("nobody-1"), "zz")
    assert (other.status, other.body) == (ghost.status, ghost.body) == ("INVALID", {"reason": "unknown_decision"})
