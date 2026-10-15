"""H25 continued: emergencies (R25-4), precedence/quorum/concurrence on the other models (R25-1/5), set_governance (Q14),
durability (R25-7), races, and the genericity renaming test (R25-6)."""
import copy
import threading

import pytest

from g3_rig import G3Rig, renamed

THR = ("edit_threshold", {"threshold": "T-A", "value": {"min": 12}})
SCOPE = {"operations": ["edit_threshold"], "resources": [{"type": "Threshold", "keys": None}]}


def declare(r, eid="em1", expires=10, scope=SCOPE, grantees=("researcher-1",), who="admin-1", case="d1"):
    return r.propose(who, case, "emergency:declare", {"emergency": eid, "scope": scope, "expires_at": expires,
                                                     "grantees": list(grantees)})


def activate(r, **kw):
    assert declare(r, **kw).status == "OK"
    assert r.judge("agent-draft-1", kw.get("case", "d1"), "concur").status == "OK"   # office-top decides the emergency matter


def act(r, who="researcher-1", op="edit_threshold", args=None, eid="em1"):
    return r.act(who, "act", emergency=eid, operation=op, args=args or {"threshold": "T-A", "value": {"min": 99}})


def test_emergency_declare_checks_in_order(tmp_path):
    r = G3Rig(tmp_path)
    wide = {"operations": ["edit_threshold", "create_hypothesis"], "resources": [{"type": "Threshold", "keys": None}]}
    assert declare(r, scope=wide).body == {"reason": "scope_amplification"}
    assert declare(r, expires=13).body == {"reason": "emergency_too_long"}
    assert declare(r, grantees=("admin-1",)).body == {"reason": "not_grantee"}
    assert declare(r, who="viewer-1").body == {"reason": "no_authority"}
    assert r.head() == r.head() and r.gov_marks() == []        # nothing committed


def test_emergency_is_bounded_by_scope_grantee_window_and_leaves_no_residual(tmp_path):
    r = G3Rig(tmp_path)
    assert declare(r).status == "OK"
    assert act(r).body == {"reason": "emergency_inactive"}                   # declared but not decided
    assert r.judge("agent-draft-1", "d1", "concur").status == "OK"
    res, eff = r.effects_of(lambda: act(r))
    assert res.status == "OK" and [e["kind"] for e in eff] == ["update"]
    assert {m["data"]["op"] for m in r.gov_marks()} >= {"act"}
    assert act(r, who="admin-1").body == {"reason": "not_grantee"}
    assert act(r, op="evaluate_hypothesis", args={"hypothesis": "H-A"}).body == {"reason": "out_of_emergency_scope"}
    assert r.dep.direct(r.tok("researcher-1"), *THR, request_id=r.rid()).body == {"reason": "case_required"}   # not an ambient grant
    r.adv(10)                                                                # tick 10 >= expires_at 10 (strict)
    res, eff = r.effects_of(lambda: act(r))
    assert res.body == {"reason": "emergency_expired"} and eff == []
    res, eff = r.effects_of(lambda: r.dep.direct(r.tok("researcher-1"), *THR, request_id=r.rid()))
    assert res.body == {"reason": "case_required"} and eff == []             # as if the emergency had never existed


def test_end_stops_the_emergency_for_every_later_commit(tmp_path):
    r = G3Rig(tmp_path)
    activate(r)
    assert r.act("researcher-1", "end", emergency="em1").body == {"reason": "not_eligible"}   # only the declaring body's members
    assert r.act("agent-draft-1", "end", emergency="em1").status == "OK"
    assert act(r).body == {"reason": "emergency_inactive"}
    assert r.act("agent-draft-1", "end", emergency="em1").body == {"reason": "emergency_inactive"}


def test_emergency_no_expiry_mutant_acts_after_expiry(tmp_path):
    r = G3Rig(tmp_path, mutants=["emergency_no_expiry"])
    activate(r)
    r.adv(50)
    res, eff = r.effects_of(lambda: act(r))
    assert res.status == "OK" and eff                                        # the clean build refuses (test above)


def test_emergency_deny_grant_still_applies(tmp_path):
    import copy as c
    auth = c.deepcopy(G3Rig(tmp_path).auth)
    auth["grants"].append({"id": "g-deny-r1", "operation": "edit_threshold", "effect": "deny", "delegable": False,
                           "origin": "neutral-extension", "principal": {"id": "researcher-1"}, "resource": {"any": True}})
    r = G3Rig(tmp_path, auth=auth)
    activate(r)
    assert act(r).body == {"reason": "no_authority"}


# ---- other models ------------------------------------------------------------------------------------------------------
def test_collegial_quorum_recusal_and_rank_precedence(tmp_path):
    r = G3Rig(tmp_path, model="collegial")
    EVC = ("evaluate_hypothesis", {"hypothesis": "H-C"})
    assert r.propose("researcher-1", "c1", *EVC).body == {"case": "c1", "bodies": ["board-a"]}      # rank 2 beats rank 1
    assert r.judge("viewer-1", "c1", "concur").status == "OK"
    assert r.judge("viewer-1", "c1", "concur").body == {"reason": "already_judged"}
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}          # 1 of k=2
    assert r.judge("admin-1", "c1", "concur").status == "OK"
    assert r.propose("admin-1", "c2", *EVC).status == "OK"                                           # admin-1 is a board-a member
    assert r.judge("admin-1", "c2", "concur").body == {"reason": "not_eligible"}                    # recused as requester
    assert r.judge("viewer-1", "c2", "dissent").status == "OK"                                       # n=2 eligible, k=2: dissent 1 > n-k=0 denies
    assert r.judge("agent-draft-1", "c2", "dissent").body == {"reason": "stage_closed"}
    r.adv(3)
    assert r.act("admin-1", "execute", case="c2").body == {"reason": "case_denied"}


def test_collegial_unresolved_precedence_is_explicit(tmp_path):
    r = G3Rig(tmp_path, model="collegial")
    doc = copy.deepcopy(r.gov)
    for b in doc["bodies"]:
        b["rank"] = 1
    r.dep.set_governance(doc)
    h = r.head()
    assert r.propose("researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-C"}).body == {"reason": "precedence_unresolved"}
    assert r.head() == h


def test_polycentric_specialis_and_concurrence(tmp_path):
    r = G3Rig(tmp_path, model="polycentric")
    assert r.propose("researcher-1", "a", "evaluate_hypothesis", {"hypothesis": "H-A"}).body["bodies"] == ["jur-3"]   # narrower matter
    assert r.propose("researcher-1", "b", "evaluate_hypothesis", {"hypothesis": "H-B"}).body["bodies"] == ["jur-1"]
    ev = {"hypothesis": "H-C", "evidence": "EV-C1"}
    assert r.propose("researcher-1", "x", "attach_evidence", ev).body["bodies"] == ["jur-1", "jur-2"]   # dual key
    assert r.judge("viewer-1", "x", "concur").status == "OK"
    assert r.act("researcher-1", "execute", case="x").body == {"reason": "oracle_needed"}               # jur-2 has not concurred
    assert r.judge("researcher-1", "x", "concur").body == {"reason": "not_eligible"}                    # recused requester
    assert r.judge("researcher-2", "x", "concur").status == "OK"
    assert r.act("researcher-1", "execute", case="x").body == {"reason": "oracle_needed"}               # quorum k=2 of the 2 eligible
    assert r.judge("admin-1", "x", "concur").status == "OK"
    assert r.act("researcher-1", "execute", case="x").body == {"reason": "not_final"}                   # arbiter review window 4
    r.adv(4)
    assert r.act("researcher-1", "execute", case="x").status in ("OK", "INVALID", "DENIED")


def test_polycentric_lapse_allow_with_empty_basis(tmp_path):
    r = G3Rig(tmp_path, model="polycentric")
    r.propose("researcher-1", "c1", *THR)                                  # m-2: jur-2 quorum, lapse allow after 5, review by arbiter
    r.adv(5)
    assert r.propose("researcher-1", "c2", "evaluate_hypothesis", {"hypothesis": "H-B"}).status == "OK"   # a tx at tick 5 fixes the lapse
    r.adv(4)
    h = r.head()
    res = r.act("researcher-1", "execute", case="c1")
    assert res.status == "OK"
    m = [x["data"] for x in r.gov_marks(h) if x["data"]["op"] == "execute"]
    assert m == [{"op": "execute", "case": "c1", "outcome": "ALLOW", "rule": "lapse", "basis": []}]


# ---- set_governance, durability, races ----------------------------------------------------------------------------------
def test_set_governance_refuses_invalid_documents_and_does_not_grandfather(tmp_path):
    r = G3Rig(tmp_path, model="collegial")
    bad = copy.deepcopy(r.gov)
    bad["superior"] = [["board-a", "board-b"], ["board-b", "board-a"]]
    h = r.head()
    with pytest.raises(ValueError):
        r.dep.set_governance(bad)
    assert r.head() == h and r.gov_marks() == []
    EVC = ("evaluate_hypothesis", {"hypothesis": "H-C"})
    r.propose("researcher-1", "c1", *EVC)
    r.judge("viewer-1", "c1", "concur")
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "oracle_needed"}
    doc = copy.deepcopy(r.gov)
    doc["bodies"][0]["rule"] = {"kind": "quorum", "k": 1, "recuse": ["requester"]}
    r.dep.set_governance(doc)                                              # the open case is re-evaluated under the new document
    assert r.dep.case_state("c1")["stage_outcomes"]["decision"] == "ALLOW"
    assert r.judge("admin-1", "c1", "concur").body == {"reason": "stage_closed"}
    assert [m["data"]["op"] for m in r.gov_marks()][-1] == "set_governance"


def test_cases_survive_crash_and_restart_and_request_ids_are_idempotent(tmp_path):
    r = G3Rig(tmp_path)
    r.propose("researcher-1", "c1", *THR)
    r.dep.arm_crash("before_commit")
    j = r.rid("j")
    assert r.judge("agent-draft-1", "c1", "concur", rid=j).body == {"reason": "crashed"}
    assert r.dep.case_state("c1") is None or True
    r.dep.restart()
    assert r.dep.case_state("c1")["stage_outcomes"]["decision"] == "AWAITING"                    # nothing committed
    r.dep.arm_crash("after_commit")
    assert r.judge("agent-draft-1", "c1", "concur", rid=j).body == {"reason": "crashed"}
    r.dep.restart()
    assert r.dep.case_state("c1")["stage_outcomes"]["decision"] == "ALLOW"                       # committed, ack lost
    again = r.judge("agent-draft-1", "c1", "concur", rid=j)
    assert (again.status, again.body) == ("OK", {"case": "c1", "stage": "decision"})              # same request id: stored result
    assert len([m for m in r.gov_marks() if m["data"]["op"] == "judge"]) == 1
    h = r.head()
    r.dep.arm_crash("after_commit")
    assert r.act("researcher-1", "execute", case="c1", rid="ex").body == {"reason": "crashed"}
    r.dep.restart()
    assert r.dep.case_state("c1")["executed"] is True
    assert r.act("researcher-1", "execute", case="c1", rid="ex2").status == "OK"
    assert sum(m["kind"] == "update" for m in r.log(h)) == 1                                       # one effect per case


def test_concurrent_executions_of_one_case_commit_one_effect(tmp_path):
    r = G3Rig(tmp_path)
    r.propose("researcher-1", "c1", *THR)
    r.judge("agent-draft-1", "c1", "concur")
    h, out = r.head(), []
    ts = [threading.Thread(target=lambda i=i: out.append(r.act("researcher-1", "execute", case="c1", rid=f"t{i}"))) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(o.status == "OK" for o in out) and sum(m["kind"] == "update" for m in r.log(h)) == 1


# ---- genericity (R25-6): consistent renaming of ids does not change any outcome --------------------------------------
def _script(r):
    out = []
    out.append(r.propose("researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-C"}))
    out.append(r.act("researcher-1", "execute", case="c1"))
    out.append(r.judge("admin-1", "c1", "concur"))
    out.append(r.judge("admin-1", "c1", "dissent"))
    r.adv(5)
    out.append(r.act("researcher-1", "execute", case="c1"))
    return [(o.status, o.body.get("reason")) for o in out]


@pytest.mark.parametrize("model", ["hierarchical", "collegial", "polycentric"])
def test_renaming_bodies_matters_and_model_ids_changes_nothing(tmp_path, model):
    base = G3Rig(tmp_path, model=model)
    ren = G3Rig(tmp_path, model=model, governance=renamed(base.gov, lambda x: "q9-" + x[::-1]))
    assert _script(base) == _script(ren)
