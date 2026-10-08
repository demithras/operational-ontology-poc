"""Each Gate 3 mutant switch (r3_shared.mutants.KNOWN["H25"/"H26"]) demonstrably breaks a frozen requirement; the same
probe passes on the clean build (control). Hand-written from PROT-H25 s6 / PROT-H26 s8."""
import pytest

from conv_g3_util import EXPEDITE, RESCHEDULE, canon, make_g3, vary
from r3_shared.disclosure import check_low_result

PL, SEN, SUP, ADM, NOB, JUN = "planner-1", "senior-1", "supervisor-1", "admin-1", "nobody-1", "junior-1"
HID, ABS = "PurchaseOrder:PO-991", "PurchaseOrder:PO-nope"
FAIL_TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 100000}


def clean_and_mut(tmp_path, mutant, fn, model="hierarchical", domain="manufacturing", governance="fixture", history=False):
    """-> (fn(clean build), fn(mutant build)) on identical, separate rigs."""
    return [fn(make_g3(tmp_path, model, domain, mutants=ms, governance=governance, sub=f"{mutant}{i}", history=history))
            for i, ms in enumerate(((), (mutant,)))]


# ---- H26 ---------------------------------------------------------------------------------------------------------------
def _split(r):
    t = r.token(JUN)
    return canon(r.dep.read_object(t, HID)) == canon(r.dep.read_object(t, ABS))


def test_existence_status_split(tmp_path):
    c, m = clean_and_mut(tmp_path, "existence_status_split", _split, governance=None)
    assert c is True and m is False


def _detail(r):
    res = r.dep.direct(r.token(PL), "transfer_inventory", FAIL_TRANSFER, None, "f1")
    assert res.status != "OK"
    return set(res.body)


def test_error_detail_leak(tmp_path):
    c, m = clean_and_mut(tmp_path, "error_detail_leak", _detail, governance=None)
    assert c <= {"reason", "rule", "input"} and "detail" in m


def _tools(r):
    return [t.name for t in r.dep.tools(r.token(NOB))]


def test_hidden_tool_schema(tmp_path):
    c, m = clean_and_mut(tmp_path, "hidden_tool_schema", _tools, governance=None)
    assert c == [] and len(m) > 0


def _prov(r):
    r.dep.direct(r.token(PL), "reschedule_work_order", RESCHEDULE, None, "rs1")
    return r.dep.prov_decision(r.token(SUP), "rs1")


def test_provenance_edge_retained_and_redaction_fabrication(tmp_path):
    c, m1, m2 = [_prov(make_g3(tmp_path, governance=None, mutants=ms, history=True, sub=f"pv{i}"))
                 for i, ms in enumerate(((), ("provenance_edge_retained",), ("redaction_fabrication",)))]
    for x in (c, m1, m2):
        check_low_result("prov_decision", x)
    assert c.body["decision"]["subject"] == {"redacted": "actor"}  # scalars level: actor withheld, EXPLICITLY
    assert m1.body["decision"]["subject"] == PL  # unredacted actor
    assert m2.body["decision"]["subject"] == "system"  # marker-free substitute = false statement
    ua = make_g3(tmp_path, governance=None, mutants=("provenance_edge_retained",), history=True, sub="ua")
    ua.dep.direct(ua.token(PL), "reschedule_work_order", RESCHEDULE, None, "rs2")
    assert ua.dep.authority_used_as(ua.token(PL), "rs2").body["authority_version"] != {"redacted": "digest"}


def _sub(r):
    t = r.token(JUN)
    sid = r.dep.subscribe(t, {"types": ["PurchaseOrder"]}).body["sub"]
    vary(r, HID, status="OPEN")
    return r.dep.poll(t, sid).body["events"]


def test_subscription_unfiltered(tmp_path):
    c, m = clean_and_mut(tmp_path, "subscription_unfiltered", _sub, governance=None)
    assert c == [] and len(m) == 1 and m[0]["ref"] == HID


# ---- H25 ---------------------------------------------------------------------------------------------------------------
def _bodies(r):
    return r.propose(ADM, "c1", "reschedule_work_order", RESCHEDULE).body["bodies"]


def test_precedence_inverted(tmp_path):
    c, m = clean_and_mut(tmp_path, "precedence_inverted", _bodies, model="collegial")
    assert c == ["board-a"] and m == ["board-b"]


def _quorum(r):
    r.propose(ADM, "c1", "reschedule_work_order", RESCHEDULE)
    r.judge(SUP, "c1", "decision", "concur")
    r.advance(4)
    return r.simple(ADM, "execute", case="c1").body


def test_quorum_weakened(tmp_path):
    c, m = clean_and_mut(tmp_path, "quorum_weakened", _quorum, model="collegial")
    assert c == {"reason": "oracle_needed"} and m.get("effects") == 1


def _noexp(r):
    from test_conv_g3_h25 import declare
    declare(r, exp=8)
    r.advance(10)
    return r.act(PL, {"kind": "act", "emergency": "EM1", "operation": "reschedule_work_order", "args": RESCHEDULE}).status


def test_emergency_no_expiry(tmp_path):
    c, m = clean_and_mut(tmp_path, "emergency_no_expiry", _noexp)
    assert c == "DENIED" and m == "OK"


def _autofill(r):
    r.propose(PL, "c1", "reschedule_work_order", RESCHEDULE)
    return r.simple(PL, "execute", case="c1")  # no judgment supplied: AWAITING, no lapse yet


def test_merit_autofill(tmp_path):
    c, m = clean_and_mut(tmp_path, "merit_autofill", _autofill)
    assert c.body == {"reason": "oracle_needed"} and m.status == "OK"
    assert r_mark_basis(tmp_path) == ["autofill:c1"]


def r_mark_basis(tmp_path):
    r = make_g3(tmp_path, mutants=("merit_autofill",), sub="mb")
    _autofill(r)
    return r.marks()[-1]["data"]["basis"]


def _domain(r):
    return r.dep.direct(r.token("researcher-1"), "evaluate_hypothesis", {"hypothesis": "H-C"}, None, "q1").body.get("reason")


def test_domain_privilege_branch(tmp_path):
    c, m = clean_and_mut(tmp_path, "domain_privilege_branch", _domain, model="collegial", domain="project")
    assert c == "case_required" and m != "case_required"
    # control: the same mutant build on the manufacturing domain behaves like the clean build
    r = make_g3(tmp_path, "collegial", "manufacturing", mutants=("domain_privilege_branch",), sub="mfg")
    assert r.dep.direct(r.token(PL), "reschedule_work_order", RESCHEDULE, None, "q2").body["reason"] == "case_required"
