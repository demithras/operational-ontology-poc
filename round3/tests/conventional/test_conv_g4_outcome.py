"""R28-4..R28-6 outcome function (P1f-6 order N,U,D1,D2,D3,S,F,W), R28-9/R28-10 observation path and stop rule."""
import pytest

from conv_g4_util import (EXPEDITE, NOTIFY, RESCHEDULE, FalseFailure, FalseSuccess, Dup, Honest, Omit, PayloadMut, TargetSubst,
                          TimeoutAfterApply, make_g4)
from conventional import extrecon
from r3_shared import outcome as oc
from r3_shared.extobs import AudRow, EffRow, ObserverFault, ObsSnapshot

I = {"operation": "expedite", "target": "po:PO-1", "payload_digest": "d1", "correlation": "r#0"}


def eff(seq, **kw):
    f = dict(seq=seq, tick=3, system="ERP", operation="expedite", target="po:PO-1", payload_digest="d1", cap_chain="c",
             correlation="r#0", adapter_id="H0")
    return EffRow(**{**f, **kw})


def aud(seq, **kw):
    f = dict(seq=seq, tick=3, system="ERP", operation="expedite", target="po:PO-1", payload_digest="d1", cap_chain="c",
             correlation="r#0", adapter_id="H0", outcome="refused", reason="uses_exhausted")
    return AudRow(**{**f, **kw})


def snap(effects=(), audit=(), through=5):
    return ObsSnapshot(through, list(effects), list(audit), through)


# (name, snapshot, prev, class, observability, expiry, expected state, expected confidence)
CASES = [
    ("N none", snap([eff(1)]), "PENDING", "at_most_once", "none", 8, "UNKNOWN", "low"),
    ("N none stays", snap([eff(1)]), "RECONCILED_SUCCESS", "at_most_once", "none", 8, "UNKNOWN", "low"),
    ("U keeps final", None, "RECONCILED_SUCCESS", "at_most_once", "full", 8, "RECONCILED_SUCCESS", "full"),
    ("U keeps failed", None, "RECONCILED_FAILED", "at_most_once", "full", 8, "RECONCILED_FAILED", "full"),
    ("U keeps diverged", None, "DIVERGED", "at_most_once", "effects_only", 8, "DIVERGED", "low"),
    ("U pending->unknown", None, "PENDING", "at_most_once", "full", 8, "UNKNOWN", "full"),
    ("D1 absorbing", snap([eff(1)]), "DIVERGED", "at_most_once", "full", 8, "DIVERGED", "full"),
    ("D2 other target", snap([eff(1, target="po:PO-2")]), "PENDING", "at_most_once", "full", 8, "DIVERGED", "full"),
    ("D2 other payload", snap([eff(1, payload_digest="zz")]), "PENDING", "at_most_once", "full", 8, "DIVERGED", "full"),
    ("D2 refused substitution audit", snap([], [aud(2, target="po:PO-2", reason="target_mismatch")]), "PENDING", "at_most_once",
     "full", 8, "DIVERGED", "full"),
    ("D2 mismatch + intended", snap([eff(1)], [aud(2, target="po:X", reason="target_mismatch")]), "PENDING", "at_most_once",
     "full", 8, "DIVERGED", "full"),
    ("D3 two applied at_most_once", snap([eff(1), eff(2)]), "PENDING", "at_most_once", "full", 8, "DIVERGED", "full"),
    ("D3 exactly_once_required", snap([eff(1), eff(2)]), "PENDING", "exactly_once_required", "full", 8, "DIVERGED", "full"),
    ("idempotent_set repeats are fine", snap([eff(1), eff(2)]), "PENDING", "idempotent_set", "effects_only", 8,
     "RECONCILED_SUCCESS", "low"),
    ("S one row", snap([eff(1)]), "PENDING", "at_most_once", "full", 8, "RECONCILED_SUCCESS", "full"),
    ("S benign refused uses_exhausted", snap([eff(1)], [aud(2)]), "PENDING", "at_most_once", "full", 8, "RECONCILED_SUCCESS", "full"),
    ("F complete past expiry", snap([], [], through=9), "PENDING", "at_most_once", "full", 8, "RECONCILED_FAILED", "full"),
    ("W window open", snap([], [], through=8), "PENDING", "at_most_once", "full", 8, "PENDING", "full"),
    ("W lagging (nothing seen yet)", snap([], [], through=2), "PENDING", "at_most_once", "full", 8, "PENDING", "full"),
    ("W benign refused only", snap([], [aud(2, reason="expired")], through=5), "PENDING", "at_most_once", "full", 8, "PENDING", "full"),
    ("effects_only is low", snap([], [], through=9), "PENDING", "idempotent_set", "effects_only", 8, "RECONCILED_FAILED", "low"),
    ("audit rows ignored when effects_only", snap([], [aud(2, target="po:X")], through=5), "PENDING", "idempotent_set",
     "effects_only", 8, "PENDING", "low"),
]


@pytest.mark.parametrize("name,s,prev,cls,obs,exp,state,conf", CASES, ids=[c[0] for c in CASES])
def test_r28_5_outcome_function_follows_p1f6_order(name, s, prev, cls, obs, exp, state, conf):
    got = extrecon.outcome_state(I, s, prev, cls, obs, exp)
    assert got[:2] == (state, conf)


def test_every_p1f6_rule_is_exercised_by_the_table():
    hit = {n.split()[0] for n, *_ in CASES}
    assert {"N", "U", "D1", "D2", "D3", "S", "F", "W"} <= hit


def test_r28_6_monotone_transition_table():
    for prev in oc.STATES:
        for new in oc.STATES:
            kept = extrecon.next_state(prev, new, "full", [], "full", [])[0]
            assert kept == (new if oc.allowed_transition(prev, new) else prev)
    assert extrecon.next_state("RECONCILED_SUCCESS", "PENDING", "full", [], "full", [])[0] == "RECONCILED_SUCCESS"


def _final(r, rid, wm=None):
    r.tick(20)
    return r.dep.reconcile(rid, wm or r.clock.now()).body["outcomes"][0]["state"]


@pytest.mark.parametrize("adapter,state", [(Honest, "RECONCILED_SUCCESS"), (FalseSuccess, "RECONCILED_FAILED"),
                                           (FalseFailure, "RECONCILED_SUCCESS"), (TimeoutAfterApply, "RECONCILED_SUCCESS"),
                                           (Omit, "RECONCILED_FAILED"), (TargetSubst, "DIVERGED"), (PayloadMut, "DIVERGED"),
                                           (Dup, "RECONCILED_SUCCESS")], ids=lambda x: getattr(x, "adapter_id", x))
def test_r28_6_truth_comes_from_the_ledger_not_the_reply(tmp_path, adapter, state):
    r = make_g4(tmp_path, default=adapter)
    assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="o1").status == "OK"
    assert _final(r, "o1") == state


def test_r28_6_false_success_stays_pending_inside_the_window(tmp_path):
    r = make_g4(tmp_path, default=FalseSuccess)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="o2")
    assert r.dep.reconcile("o2", r.clock.now()).body["outcomes"][0]["state"] == "PENDING"


def test_r28_10_effects_only_system_is_low_confidence(tmp_path):
    r = make_g4(tmp_path)
    r.dep.call_tool(r.token("planner-1"), "reschedule_work_order", RESCHEDULE, request_id="m1")
    o = r.dep.reconcile("m1", r.clock.now()).body["outcomes"][0]
    assert (o["state"], o["confidence"]) == ("RECONCILED_SUCCESS", "low")


def test_r28_10_effects_only_hides_refused_substitution(tmp_path):
    r = make_g4(tmp_path, adapters={"MES": TargetSubst})
    r.dep.call_tool(r.token("planner-1"), "reschedule_work_order", RESCHEDULE, request_id="m2")
    o = r.dep.reconcile("m2", r.clock.now() + 20).body["outcomes"][0]
    assert o["state"] == "RECONCILED_FAILED" and o["confidence"] == "low"      # refused attempt is invisible on this path


def test_r28_10_none_class_stays_unknown_low_for_ever(tmp_path):
    r = make_g4(tmp_path)
    svc = r.dep.service
    h = svc.factory("conventional-service")
    try:
        svc._ext.enqueue(h, "gn1", [{"adapter": "GEN-NULL", "target": "record", "payload": {"key": "k1"}}], r.clock.now())
        svc._ext.dispatch(h, lambda _: "", r.clock.now())
    finally:
        h.close()
    assert len(r.ledger()) == 1                                    # the effect really happened
    for wm in (r.clock.now(), r.clock.now() + 30):
        o = r.dep.reconcile("gn1", wm).body["outcomes"][0]
        assert (o["state"], o["confidence"]) == ("UNKNOWN", "low")


def test_r28_9_observer_unavailable_keeps_final_state_never_errors(tmp_path):
    r = make_g4(tmp_path)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="u1")
    assert r.dep.reconcile("u1", r.clock.now()).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"
    r.observer.fault = ObserverFault.unavailable()
    res = r.dep.reconcile("u1", r.clock.now())
    assert res.status == "OK" and res.body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"


def test_r28_9_observer_unavailable_before_truth_is_unknown(tmp_path):
    r = make_g4(tmp_path, fault=ObserverFault.unavailable())
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="u2")
    res = r.dep.reconcile("u2", r.clock.now())
    assert res.status == "OK" and res.body["outcomes"][0]["state"] == "UNKNOWN"


def test_r28_9_lagging_observer_is_pending_not_failed(tmp_path):
    r = make_g4(tmp_path, fault=ObserverFault.lagging(30))
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="u3")
    r.tick(20)
    assert r.dep.reconcile("u3", r.clock.now()).body["outcomes"][0]["state"] == "PENDING"


def test_reconcile_and_outcome_unknown_request(tmp_path):
    r = make_g4(tmp_path)
    assert r.dep.reconcile("nope", 3).body == {"reason": "unknown_request"}
    assert r.dep.outcome("nope").status == "INVALID"
    r.dep.call_tool(r.token("planner-1"), "create_hypothesis" if False else "expedite_purchase_order", EXPEDITE, request_id="k")
    o = r.dep.outcome("k").body["outcomes"][0]
    assert set(o) == set(oc.KEYS) and o["state"] == "PENDING"
    oc.validate_outcomes(r.dep.reconcile("k", r.clock.now()).body)
