"""H25 (PROT-H25 s2-s3): the constitutional procedure on the hierarchical model, project domain. Effects are measured from the
world store (WorldReader diff / world_log), never from return values."""
import pytest

from g3_rig import G3Rig

EV = ("evaluate_hypothesis", {"hypothesis": "H-A"})
THR = ("edit_threshold", {"threshold": "T-A", "value": {"min": 11}})


@pytest.fixture
def rig(tmp_path):
    return G3Rig(tmp_path)


def test_propose_reports_deciding_body_and_writes_one_governance_mark(rig):
    h = rig.head()
    res, eff = rig.effects_of(lambda: rig.propose("researcher-1", "c1", *EV))
    assert (res.status, res.body) == ("OK", {"case": "c1", "bodies": ["office-lead"]}) and eff == []
    marks = rig.gov_marks(h)
    assert len(marks) == 1 and marks[0]["data"]["op"] == "propose" and marks[0]["data"]["bodies"] == ["office-lead"]
    assert set(marks[0]["data"]) == {"op", "case", "requester", "on_behalf_of", "operation", "args_digest", "bodies"}


def test_refusals_write_nothing_and_follow_the_frozen_order(rig):
    h = rig.head()
    assert rig.dep.constitutional("bad-token", {"kind": "appeal", "case": "x"}, "r0").status == "DENIED"
    assert rig.act("researcher-1", "appeal", case="x", extra=1).body == {"reason": "schema"}
    assert rig.propose("researcher-1", "c1", "no_such_op", {}).body == {"reason": "schema"}
    assert rig.propose("researcher-1", "c1", "create_hypothesis", {"claim": "x"}).body == {"reason": "not_governed"}
    assert rig.propose("viewer-1", "c1", *EV).body == {"reason": "no_authority"}
    assert rig.judge("viewer-1", "nope", "concur").body == {"reason": "unknown_case"}
    assert rig.gov_marks(h) == [] and rig.head() == h
    assert rig.propose("researcher-1", "c1", *EV).status == "OK"
    assert rig.propose("researcher-1", "c1", *EV).body == {"reason": "duplicate_case"}


def test_governed_request_without_a_case_is_refused_with_zero_effects(rig):
    for via in ("direct", "call_tool"):
        res, eff = rig.effects_of(lambda: getattr(rig.dep, via)(rig.tok("researcher-1"), *EV, request_id=rig.rid()))
        assert (res.status, res.body["reason"]) == ("DENIED", "case_required") and eff == []
    res, eff = rig.effects_of(lambda: rig.dep.direct(rig.tok("researcher-1"), "create_hypothesis", {"claim": "free"}, request_id=rig.rid()))
    assert res.status == "OK" and len(eff) == 1   # ungoverned requests are decided exactly as before


def test_execute_needs_final_allow_then_commits_the_effect_with_marks(rig):
    rig.propose("researcher-1", "c1", *EV)
    assert rig.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}          # no judgment: AWAITING
    assert rig.judge("researcher-1", "c1", "concur").body == {"reason": "not_eligible"}                # the requester sees the case but is no member
    assert rig.judge("admin-1", "c1", "concur").body == {"reason": "not_eligible"}                     # reviewer, not a deciding body member
    assert rig.judge("agent-evidence-1", "c1", "concur").body == {"reason": "unknown_case"}            # cannot see the case at all
    r = rig.rid("j")
    assert rig.judge("viewer-1", "c1", "concur", merit="free text", rid=r).status == "OK"
    assert rig.act("researcher-1", "execute", case="c1").body == {"reason": "not_final"}               # review window open
    assert rig.judge("viewer-1", "c1", "dissent").body == {"reason": "stage_closed"}
    # a case whose matter has a review window that elapses, on an operation that succeeds (H-C: m-broad decided by admin-1)
    rig.propose("researcher-1", "c2", "evaluate_hypothesis", {"hypothesis": "H-C"})
    r2 = rig.rid("j")
    rig.judge("admin-1", "c2", "concur", rid=r2)
    rig.adv(5)
    h = rig.head()
    res, eff = rig.effects_of(lambda: rig.act("researcher-1", "execute", case="c2", rid="ex1"))
    kinds = {m["ref"]: m["data"] for m in rig.log(h) if m["kind"] == "mark"}
    assert kinds["governance"] == {"op": "execute", "case": "c2", "outcome": "ALLOW", "rule": "decision", "basis": [r2]}
    assert res.status == "OK" and "commit" in kinds and eff                                             # effects + both marks, one transaction
    again, eff2 = rig.effects_of(lambda: rig.act("researcher-1", "execute", case="c2", rid="ex2"))
    assert (again.status, again.body) == (res.status, res.body) and eff2 == []                          # stored result by case; one effect per case


def test_merit_never_changes_an_outcome(tmp_path):
    outs = []
    for merit in ("yes please", "", "x" * 500):
        r = G3Rig(tmp_path)
        r.propose("researcher-1", "c1", *EV)
        r.judge("viewer-1", "c1", "dissent", merit=merit)
        r.adv(3)
        outs.append(r.act("researcher-1", "execute", case="c1").body)
    assert outs == [{"reason": "case_denied"}] * 3


def test_lapse_applies_only_where_the_document_declares_it(tmp_path):
    r = G3Rig(tmp_path)                       # m-narrow: lapse deny after 4
    r.propose("researcher-1", "c1", *EV)
    r.adv(3)
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}
    r.adv(1)                                  # tick 4 >= 0 + 4: DENY by lapse, fixed at the next transaction; window 3 still open
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "not_final"}
    assert r.propose("researcher-1", "c2", "edit_threshold", {"threshold": "T-A", "value": {"min": 1}}).status == "OK"  # tx at tick 4 fixes it
    r.adv(3)
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "case_denied"}
    assert r.judge("viewer-1", "c1", "concur").body == {"reason": "stage_closed"}
    p = G3Rig(tmp_path, model="polycentric")  # m-1 awaits forever (no lapse) for evaluate_hypothesis
    p.propose("researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-B"})
    p.adv(100)
    assert p.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}


def test_appeal_overturn_flips_the_outcome_and_the_basis_cites_both_stages(rig):
    op = ("evaluate_hypothesis", {"hypothesis": "H-C"})   # m-broad: decided by office-mid (admin-1), review by office-top (agent-draft-1)
    rig.propose("researcher-1", "c1", *op)
    j1 = rig.rid("j")
    rig.judge("admin-1", "c1", "dissent", rid=j1)
    assert rig.act("agent-draft-1", "appeal", case="c1").body == {"reason": "not_party"}              # the reviewer is no party
    assert rig.act("researcher-1", "appeal", case="c1").status == "OK"
    assert rig.act("admin-1", "appeal", case="c1").body == {"reason": "already_appealed"}
    assert rig.judge("researcher-1", "c1", "uphold", stage="review").body == {"reason": "not_eligible"}
    assert rig.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}            # appealed, review AWAITING
    j2 = rig.rid("j")
    assert rig.judge("agent-draft-1", "c1", "overturn", stage="review", rid=j2).status == "OK"
    assert rig.judge("agent-draft-1", "c1", "uphold", stage="review").body == {"reason": "stage_closed"}
    h = rig.head()
    res = rig.act("researcher-1", "execute", case="c1")
    m = [x for x in rig.gov_marks(h) if x["data"]["op"] == "execute"]
    assert res.status == "OK" and len(m) == 1 and m[0]["data"]["rule"] == "review" and m[0]["data"]["basis"] == [j1, j2]


def test_window_closed_and_not_reviewable(rig):
    rig.propose("researcher-1", "c1", *EV)
    rig.judge("viewer-1", "c1", "concur")
    rig.adv(3)
    assert rig.act("researcher-1", "appeal", case="c1").body == {"reason": "window_closed"}
    rig.propose("researcher-1", "c2", "edit_threshold", {"threshold": "T-A", "value": {"min": 12}})   # m-po has no review
    rig.judge("agent-draft-1", "c2", "concur")
    assert rig.act("researcher-1", "appeal", case="c2").body == {"reason": "not_reviewable"}
    assert rig.act("researcher-1", "execute", case="c2").status in ("OK", "INVALID", "DENIED")
    assert rig.act("agent-draft-1", "execute", case="c2").body == {"reason": "not_requester"}
    assert rig.act("viewer-1", "execute", case="c2").body == {"reason": "unknown_case"}
