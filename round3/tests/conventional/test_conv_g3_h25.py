"""PROT-H25 requirements R25-1..R25-8 (conventional): hand-written expectations from the frozen text; every refusal
asserts the exact frozen body AND zero world effects."""
import pytest

from conv_g3_util import EXPEDITE, RESCHEDULE, make_g3, no_effect_refusal, refused
from r3_shared import constitutional as K
from r3_shared.world import diff

PL, SUP, SEN, ADM, JUN, NOB = "planner-1", "supervisor-1", "senior-1", "admin-1", "junior-1", "nobody-1"


def mk(tmp_path, model="hierarchical", **kw):
    return make_g3(tmp_path, model, **kw)


# ---- R25-1 procedural equality: status class, reason, mark ----------------------------------------------------
def test_r25_1_happy_path_marks_are_exactly_the_frozen_forms(tmp_path):
    r = mk(tmp_path)
    assert r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE, rid="p1").body == {"case": "c1", "bodies": ["office-mid"]}
    assert r.judge(SEN, "c1", "decision", "concur", merit="secret", rid="j1").status == "OK"
    r.advance(6)
    ex = r.simple(PL, "execute", case="c1", rid="x1")
    assert ex.status == "OK" and ex.body["effects"] == 1
    marks = [m["data"] for m in r.marks()]
    for m in marks:
        K.check_mark(m)
    assert marks[0] == K.governance_mark("propose", case="c1", requester=PL, on_behalf_of=None,
                                         operation="reschedule_work_order", args=RESCHEDULE, bodies=["office-mid"])
    assert marks[1] == K.governance_mark("judge", case="c1", stage="decision", judge=SEN, value="concur", merit="secret")
    assert marks[2] == K.governance_mark("execute", case="c1", rule="decision", basis=["j1"])
    commits = r.marks("commit")
    assert commits and commits[-1]["data"]["request_id"] == "x1"


@pytest.mark.parametrize("action,reason", [
    ({"kind": "nope"}, "schema"), ({"kind": "judge", "case": "c", "stage": "decision", "value": "uphold", "merit": ""}, "schema"),
    ({"kind": "appeal", "case": "c", "extra": 1}, "schema"), ("x", "schema")])
def test_r25_1_schema_refusals(tmp_path, action, reason):
    r = mk(tmp_path)
    no_effect_refusal(r, lambda: r.act(PL, action), "INVALID", reason)


def test_r25_1_token_and_no_governance(tmp_path):
    r = mk(tmp_path)
    no_effect_refusal(r, lambda: r.dep.constitutional("bad", {"kind": "appeal", "case": "c"}, "r1"), "DENIED", "token")
    r2 = mk(tmp_path, governance=None, sub="n")
    refused(r2.act(PL, {"kind": "appeal", "case": "c"}), "INVALID", "no_governance")


def test_r25_1_check_order_schema_before_everything(tmp_path):
    r = mk(tmp_path)  # a bad token AND a bad schema -> token first
    refused(r.dep.constitutional("bad", {"kind": "zzz"}, "r1"), "DENIED", "token")


def test_r25_1_propose_refusals_in_frozen_order(tmp_path):
    r = mk(tmp_path)
    assert r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE).status == "OK"
    no_effect_refusal(r, lambda: r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE), "INVALID", "duplicate_case")
    no_effect_refusal(r, lambda: r.propose(PL, "c2", "reschedule_work_order", {"bogus": 1}), "INVALID", "schema")
    no_effect_refusal(r, lambda: r.propose(PL, "c3", "transfer_inventory",
                                           {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17",
                                            "quantity": 1}), "INVALID", "not_governed")
    no_effect_refusal(r, lambda: r.propose(NOB, "c4", "reschedule_work_order", RESCHEDULE), "DENIED", "no_authority")


def test_r25_1_unknown_case_hides_foreign_cases(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    for who in (NOB, JUN):  # cannot see the case
        for kind, kw in (("judge", dict(stage="decision", value="concur", merit="")), ("appeal", {}), ("execute", {})):
            no_effect_refusal(r, lambda: r.simple(who, kind, case="c1", **kw), "INVALID", "unknown_case")
    no_effect_refusal(r, lambda: r.simple(SEN, "execute", case="zz"), "INVALID", "unknown_case")


def test_r25_1_judge_refusals(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    no_effect_refusal(r, lambda: r.judge(ADM, "c1", "decision", "concur"), "DENIED", "not_eligible")
    no_effect_refusal(r, lambda: r.judge(SEN, "c1", "review", "uphold"), "DENIED", "not_eligible")  # no appeal yet
    assert r.judge(SEN, "c1", "decision", "abstain").status == "OK"
    no_effect_refusal(r, lambda: r.judge(SEN, "c1", "decision", "concur"), "INVALID", "already_judged")


def test_r25_1_execute_refusals(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    no_effect_refusal(r, lambda: r.simple(PL, "execute", case="c1"), "DENIED", "oracle_needed")
    no_effect_refusal(r, lambda: r.simple(SEN, "execute", case="c1"), "DENIED", "not_requester")
    r.judge(SEN, "c1", "decision", "dissent")
    no_effect_refusal(r, lambda: r.simple(PL, "execute", case="c1"), "DENIED", "not_final")
    r.advance(6)
    no_effect_refusal(r, lambda: r.simple(PL, "execute", case="c1"), "DENIED", "case_denied")
    no_effect_refusal(r, lambda: r.judge(SEN, "c1", "decision", "concur"), "INVALID", "stage_closed")


def test_r25_1_appeal_flow_overturn(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    r.judge(SEN, "c1", "decision", "dissent")
    no_effect_refusal(r, lambda: r.simple(NOB, "appeal", case="c1"), "INVALID", "unknown_case")
    no_effect_refusal(r, lambda: r.simple(ADM, "appeal", case="c1"), "DENIED", "not_party")  # sees it (reviewer)
    assert r.simple(PL, "appeal", case="c1").status == "OK"
    no_effect_refusal(r, lambda: r.simple(PL, "appeal", case="c1"), "INVALID", "already_appealed")
    assert r.judge(ADM, "c1", "review", "overturn", rid="rv").status == "OK"
    ex = r.simple(PL, "execute", case="c1")
    assert ex.status == "OK"
    assert r.marks()[-1]["data"]["rule"] == "review" and r.marks()[-1]["data"]["basis"][-1] == "rv"


def test_r25_1_appeal_window_is_strict(tmp_path):
    r = mk(tmp_path)  # decided at tick 2, window 5 for m-broad -> appeal ok at tick 6, closed at 7
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    r.judge(SEN, "c1", "decision", "dissent")
    r.advance(5)
    no_effect_refusal(r, lambda: r.simple(PL, "appeal", case="c1"), "DENIED", "window_closed")
    no_effect_refusal(r, lambda: r.simple(PL, "appeal", case="zz"), "INVALID", "unknown_case")


def test_r25_1_not_reviewable_and_not_decided(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    no_effect_refusal(r, lambda: r.simple(PL, "appeal", case="c1"), "INVALID", "not_decided")
    r.propose(ADM, "e1", "emergency:declare", {"emergency": "E", "scope": {"operations": ["reschedule_work_order"],
             "resources": [{"type": "WorkOrder", "keys": None}]}, "expires_at": 6, "grantees": [PL]})
    no_effect_refusal(r, lambda: r.simple(ADM, "appeal", case="e1"), "INVALID", "not_reviewable")


# ---- lapse (s2.5) is procedural, never a judgment ---------------------------------------------------------------
def test_r25_3_lapse_cites_no_judgment_and_denies(tmp_path):
    r = mk(tmp_path)  # m-broad: lapse deny after 6
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    r.advance(6)
    st = r.dep.case_state("c1")
    assert st["stage_outcomes"]["decision"] == "DENY" and st["final"] == "NOT_FINAL"
    no_effect_refusal(r, lambda: r.judge(SEN, "c1", "decision", "concur"), "INVALID", "stage_closed")
    assert r.propose(PL, "c2", "reschedule_work_order", RESCHEDULE).status == "OK"  # first transaction at tick >= 8
    r.advance(10)
    no_effect_refusal(r, lambda: r.simple(PL, "execute", case="c1"), "DENIED", "case_denied")


def test_r25_3_polycentric_lapse_allow_has_empty_basis(tmp_path):
    r = mk(tmp_path, "polycentric")
    assert r.propose(PL, "c1", "expedite_purchase_order", EXPEDITE).status == "OK"  # jur-2 (quorum), lapse allow after 5
    r.advance(5)
    assert r.propose(PL, "c2", "reschedule_work_order", RESCHEDULE).status == "OK"  # a transaction at tick 7 fixes the lapse
    r.advance(4)  # review window 4 elapsed after the lapse tick
    ex = r.simple(PL, "execute", case="c1")
    assert ex.status == "OK", ex
    m = r.marks()[-1]["data"]
    assert (m["rule"], m["basis"]) == ("lapse", [])


# ---- R25-2 / R25-5: no effect without legitimacy, explicit unresolved ---------------------------------------------
def test_r25_2_governed_call_without_case_is_refused_with_zero_effects(tmp_path):
    r = mk(tmp_path)
    for fn in (lambda: r.dep.direct(r.token(PL), "reschedule_work_order", RESCHEDULE, None, "d1"),
               lambda: r.dep.call_tool(r.token(PL), "reschedule_work_order", RESCHEDULE, None, "d2")):
        no_effect_refusal(r, fn, "DENIED", "case_required")


def test_r25_2_ungoverned_requests_unchanged(tmp_path):
    r = mk(tmp_path)
    res = r.dep.direct(r.token(PL), "transfer_inventory", {"source_warehouse": "WH-B", "destination_warehouse": "WH-A",
                                                           "part": "PX-17", "quantity": 10}, None, "u1")
    assert res.status == "OK"


def test_r25_5_precedence_unresolved_is_explicit(tmp_path):
    gov = make_g3(tmp_path, "collegial", sub="g").gov
    import copy
    d = copy.deepcopy(gov)
    d["bodies"][0]["rank"] = d["bodies"][1]["rank"]  # board-a ties board-b -> rank cannot decide
    r = make_g3(tmp_path, governance=d, sub="t")
    no_effect_refusal(r, lambda: r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE), "DENIED", "precedence_unresolved")


def test_r25_5_collegial_quorum_and_recusal(tmp_path):
    r = mk(tmp_path, "collegial")  # m-a vs m-b -> rank -> board-a (supervisor, senior, admin; k=2; recuse requester)
    assert r.propose(ADM, "c1", "reschedule_work_order", RESCHEDULE).body["bodies"] == ["board-a"]
    no_effect_refusal(r, lambda: r.judge(ADM, "c1", "decision", "concur"), "DENIED", "not_eligible")  # recused
    assert r.judge(SUP, "c1", "decision", "concur", rid="a").status == "OK"
    no_effect_refusal(r, lambda: r.simple(ADM, "execute", case="c1"), "DENIED", "oracle_needed")  # 1 of k=2
    assert r.judge(SEN, "c1", "decision", "concur", rid="b").status == "OK"
    r.advance(4)
    assert r.simple(ADM, "execute", case="c1").status == "OK"
    assert r.marks()[-1]["data"]["basis"] == ["a", "b"]


def test_r25_3_merit_never_changes_outcome(tmp_path):
    outs = []
    for i, merit in enumerate(("approve!!", "totally-reject", "")):
        r = mk(tmp_path, "collegial", sub=f"m{i}")
        r.propose(ADM, "c1", "reschedule_work_order", RESCHEDULE)
        r.judge(SUP, "c1", "decision", "concur", merit=merit)
        outs.append(r.dep.case_state("c1")["stage_outcomes"])
    assert outs[0] == outs[1] == outs[2] == {"decision": "AWAITING", "review": None}


def test_r25_3_single_abstain_stays_awaiting_not_defaulted(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    r.judge(SEN, "c1", "decision", "abstain")
    r.advance(3)
    no_effect_refusal(r, lambda: r.simple(PL, "execute", case="c1"), "DENIED", "oracle_needed")


# ---- emergencies (3.5, R25-4) --------------------------------------------------------------------------------
SCOPE = {"operations": ["reschedule_work_order"], "resources": [{"type": "WorkOrder", "keys": None}]}


def declare(r, exp=8, scope=SCOPE, grantees=(PL,), case="e1", who=ADM, eid="EM1", decide=True):
    res = r.propose(who, case, "emergency:declare", {"emergency": eid, "scope": scope, "expires_at": exp,
                                                     "grantees": list(grantees)})
    if res.status == "OK" and decide:
        assert r.judge(ADM, case, "decision", "concur").status == "OK"  # decided like any case (office-top)
    return res


def test_r25_4_declare_refusals(tmp_path):
    r = mk(tmp_path)
    wide = {"operations": ["transfer_inventory"], "resources": [{"type": "Warehouse", "keys": None}]}
    no_effect_refusal(r, lambda: declare(r, scope=wide), "DENIED", "scope_amplification")
    no_effect_refusal(r, lambda: declare(r, exp=2 + 13), "INVALID", "emergency_too_long")
    no_effect_refusal(r, lambda: declare(r, grantees=(SEN,)), "DENIED", "not_grantee")
    no_effect_refusal(r, lambda: declare(r, who=PL), "DENIED", "no_authority")


def test_r25_4_act_bounds_and_expiry(tmp_path):
    r = mk(tmp_path)
    assert declare(r, exp=8).status == "OK"
    act = {"kind": "act", "emergency": "EM1", "operation": "reschedule_work_order", "args": RESCHEDULE}
    assert r.act(PL, act).status == "OK" and len(r.snap()["effects"]) == 1  # one external MES effect
    no_effect_refusal(r, lambda: r.act(SEN, {**act, "args": {**RESCHEDULE, "new_planned_start": 36}}), "DENIED", "not_grantee")
    no_effect_refusal(r, lambda: r.act(PL, {**act, "operation": "expedite_purchase_order", "args": EXPEDITE}),
                      "DENIED", "out_of_emergency_scope")
    no_effect_refusal(r, lambda: r.act(PL, {**act, "emergency": "NOPE"}), "DENIED", "emergency_inactive")
    r.advance(6)  # tick 8 == expires_at: strict
    no_effect_refusal(r, lambda: r.act(PL, {**act, "args": {**RESCHEDULE, "new_planned_start": 37}}), "DENIED",
                      "emergency_expired")


def test_r25_4_end_and_no_residual(tmp_path):
    r = mk(tmp_path)
    declare(r)
    no_effect_refusal(r, lambda: r.simple(PL, "end", emergency="EM1"), "DENIED", "not_grantee")  # not the declaring body
    assert r.simple(ADM, "end", emergency="EM1").body == {"emergency": "EM1"}
    act = {"kind": "act", "emergency": "EM1", "operation": "reschedule_work_order", "args": RESCHEDULE}
    no_effect_refusal(r, lambda: r.act(PL, act), "DENIED", "emergency_inactive")
    no_effect_refusal(r, lambda: r.dep.direct(r.token(PL), "reschedule_work_order", RESCHEDULE, None, "z"),
                      "DENIED", "case_required")  # nothing granted survives


# ---- set_governance (3.6, Q14: no grandfathering) ---------------------------------------------------------------
def test_r25_set_governance_validates_and_reevaluates(tmp_path):
    import copy
    r = mk(tmp_path)
    bad = copy.deepcopy(r.gov)
    bad["superior"] = [["office-lead", "office-mid"], ["office-mid", "office-lead"]]
    before = len(r.reader.log())
    with pytest.raises(ValueError):
        r.dep.set_governance(bad)
    assert len(r.reader.log()) == before
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    new = copy.deepcopy(r.gov)
    new["matters"][1]["competent"] = ["office-top"]  # m-broad now decided by admin-1
    new["matters"][1]["review"] = {"by": "office-mid", "window": 5}
    r.dep.set_governance(new)
    assert r.marks()[-1]["data"]["op"] == "set_governance"
    no_effect_refusal(r, lambda: r.judge(SEN, "c1", "decision", "concur"), "DENIED", "not_eligible")
    assert r.judge(ADM, "c1", "decision", "concur").status == "OK"


# ---- R25-7 durability / idempotency ------------------------------------------------------------------------------
def test_r25_7_idempotent_retry_and_key_reuse(tmp_path):
    r = mk(tmp_path)
    a = r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE, rid="same")
    n = len(r.marks())
    assert r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE, rid="same") == a and len(r.marks()) == n
    no_effect_refusal(r, lambda: r.propose(PL, "c9", "reschedule_work_order", RESCHEDULE, rid="same"),
                      "INVALID", "idempotency_key_reuse")


def test_r25_7_crash_restart_keeps_cases_and_one_effect(tmp_path):
    r = mk(tmp_path)
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    r.judge(SEN, "c1", "decision", "concur")
    r.advance(6)
    r.dep.arm_crash("after_commit")
    assert r.simple(PL, "execute", case="c1", rid="x").status == "UNKNOWN"
    assert r.simple(PL, "execute", case="c1", rid="x2").status == "UNAVAILABLE"
    r.dep.restart()
    again = r.simple(PL, "execute", case="c1", rid="x")
    assert again.status == "OK" and r.dep.case_state("c1")["executed"]
    assert len([m for m in r.marks() if m["data"]["op"] == "execute"]) == 1
    r.dep.arm_crash("before_commit")
    before = r.snap()
    assert r.propose(PL, "c2", "reschedule_work_order", RESCHEDULE).status == "UNKNOWN"
    assert diff(before, r.snap()) == [] and r.dep.restart() is None
    assert r.dep.case_state("c2") is None and r.dep.case_state("c1")["executed"]


# ---- R25-6 genericity: every model on both domains, same code ---------------------------------------------------------
@pytest.mark.parametrize("model", ["hierarchical", "collegial", "polycentric"])
@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r25_6_every_model_loads_and_routes_on_both_domains(tmp_path, model, domain):
    r = make_g3(tmp_path, model, domain)
    st = r.dep.case_state("nope")
    assert st is None
    assert r.act("admin-1", {"kind": "appeal", "case": "x"}).body == {"reason": "unknown_case"}


def test_r25_6_renaming_invariance(tmp_path):
    import copy
    base = mk(tmp_path, sub="a")
    ren = copy.deepcopy(base.gov)
    mp = {"office-lead": "zz1", "office-mid": "zz2", "office-top": "zz3", "responders": "zz4"}
    ren["model"] = "other"
    ren["bodies"] = [{**b, "id": mp[b["id"]]} for b in ren["bodies"]]
    ren["superior"] = [[mp[a], mp[b]] for a, b in ren["superior"]]
    for m in ren["matters"]:
        m["competent"] = [mp[c] for c in m["competent"]]
        m["review"] = m["review"] and {**m["review"], "by": mp[m["review"]["by"]]}
    ren["emergency"]["grantees_from"] = mp[ren["emergency"]["grantees_from"]]
    other = make_g3(tmp_path, governance=ren, sub="b")
    out = []
    for r in (base, other):
        res = [r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE).status, r.judge(SEN, "c1", "decision", "concur").status]
        r.advance(6)
        res.append(r.simple(PL, "execute", case="c1").status)
        out.append(res)
    assert out[0] == out[1] == ["OK", "OK", "OK"]


# ---- R25-8 safe progress ---------------------------------------------------------------------------------------------
def test_r25_8_legitimate_flow_always_commits(tmp_path):
    for model, who, op, args, judges in (("hierarchical", PL, "reschedule_work_order", RESCHEDULE, [SEN]),
                                         ("collegial", ADM, "reschedule_work_order", RESCHEDULE, [SUP, SEN])):
        r = mk(tmp_path, model, sub=model)
        assert r.propose(who, "c1", op, args).status == "OK"
        assert all(r.judge(j, "c1", "decision", "concur").status == "OK" for j in judges)
        r.advance(6)
        assert r.simple(who, "execute", case="c1").status == "OK"
