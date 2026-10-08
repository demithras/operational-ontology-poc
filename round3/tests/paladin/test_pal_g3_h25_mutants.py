"""H25 mutants (KNOWN["H25"]): each one is constructor-activated and demonstrably changes behaviour on the same scenario that
the clean build handles correctly."""
from g3_rig import G3Rig

THR = ("edit_threshold", {"threshold": "T-A", "value": {"min": 12}})
EVC = ("evaluate_hypothesis", {"hypothesis": "H-C"})


def _quorum(tmp_path, mutants):
    r = G3Rig(tmp_path, model="collegial", mutants=mutants)
    r.propose("researcher-1", "c1", *EVC)
    r.judge("viewer-1", "c1", "concur")                # 1 concurrence of k=2
    return r


def test_quorum_weakened(tmp_path):
    clean, mut = _quorum(tmp_path, ()), _quorum(tmp_path, ["quorum_weakened"])
    assert clean.dep.case_state("c1")["stage_outcomes"]["decision"] == "AWAITING"
    assert mut.dep.case_state("c1")["stage_outcomes"]["decision"] == "ALLOW"


def test_precedence_inverted(tmp_path):
    clean = G3Rig(tmp_path, model="collegial").propose("researcher-1", "c1", *EVC).body["bodies"]
    mut = G3Rig(tmp_path, model="collegial", mutants=["precedence_inverted"]).propose("researcher-1", "c1", *EVC).body["bodies"]
    assert clean == ["board-a"] and mut == ["board-b"]
    h_clean = G3Rig(tmp_path, model="hierarchical").propose("researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-A"})
    h_mut = G3Rig(tmp_path, model="hierarchical", mutants=["precedence_inverted"]).propose(
        "researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-A"})
    assert h_clean.body["bodies"] == ["office-lead"] and h_mut.body["bodies"] != h_clean.body["bodies"]


def test_merit_autofill(tmp_path):
    for mutants, expect in (((), "oracle_needed"), (["merit_autofill"], None)):
        r = G3Rig(tmp_path, mutants=mutants)
        r.propose("researcher-1", "c1", *THR)
        res, eff = r.effects_of(lambda: r.act("researcher-1", "execute", case="c1"))
        if expect:
            assert res.body == {"reason": expect} and eff == []
        else:   # a missing judgment defaults to yes: the effect commits with a synthesized (empty) basis
            m = [x["data"] for x in r.gov_marks() if x["data"]["op"] == "execute"]
            assert res.status == "OK" and eff and m[0]["basis"] == []


def test_emergency_no_expiry(tmp_path):
    for mutants, ok in (((), False), (["emergency_no_expiry"], True)):
        r = G3Rig(tmp_path, mutants=mutants)
        r.propose("admin-1", "d1", "emergency:declare", {"emergency": "e", "scope": {"operations": ["edit_threshold"],
                  "resources": [{"type": "Threshold", "keys": None}]}, "expires_at": 5, "grantees": ["researcher-1"]})
        r.judge("agent-draft-1", "d1", "concur")
        r.adv(6)
        res = r.act("researcher-1", "act", emergency="e", operation=THR[0], args=THR[1])
        assert (res.status == "OK") is ok


def test_domain_privilege_branch(tmp_path):
    for mutants, ok in (((), False), (["domain_privilege_branch"], True)):
        r = G3Rig(tmp_path, mutants=mutants)
        res, eff = r.effects_of(lambda: r.dep.direct(r.tok("researcher-1"), *THR, request_id=r.rid()))
        assert (res.status == "OK" and bool(eff)) is ok
    # the branch is on the requester id and the domain name only: another principal id is still refused
    r = G3Rig(tmp_path, mutants=["domain_privilege_branch"])
    assert r.dep.direct(r.tok("researcher-2"), *THR, request_id=r.rid()).body == {"reason": "case_required"}
