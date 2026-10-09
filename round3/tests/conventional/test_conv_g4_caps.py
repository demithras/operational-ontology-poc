"""R28-7/R28-8 retry and redelivery, R28-13 per-effect attenuation, restart/crash redelivery (C28-3, C28-6)."""
import pytest

from conv_g4_util import (EXPEDITE, NOTIFY, PUBLISH_PRIVATE, RESCHEDULE, TRANSFER, Dup, Honest, Omit, TimeoutAfterApply, make_g4)
from r3_shared import extcap
from r3_shared.extadapter import correlation, payload_digest, validate_request

OPS = [("manufacturing", "planner-1", "transfer_inventory", TRANSFER, "WMS", "transfer", "transfer:PX-17@WH-B->WH-A", 1),
       ("manufacturing", "planner-1", "expedite_purchase_order", EXPEDITE, "ERP", "expedite", "po:PO-991", 1),
       ("manufacturing", "planner-1", "reschedule_work_order", RESCHEDULE, "MES", "reschedule", "wo:WO-43", 3),
       ("project", "researcher-1", "publish_result", PUBLISH_PRIVATE, "REGISTRY", "publish", "registry:verdict-H-D-1", 1),
       ("project", "researcher-1", "notify_reviewer", NOTIFY, "NOTIFY", "notify", "notify:researcher-2", 3)]


@pytest.mark.parametrize("domain,who,op,args,system,eop,target,uses", OPS, ids=[o[2] for o in OPS])
def test_c28_3_cap_carries_exactly_the_frozen_caveats(tmp_path, domain, who, op, args, system, eop, target, uses):
    r = make_g4(tmp_path, domain)
    res = r.dep.call_tool(r.token(who), op, args, request_id="c1")
    assert res.status == "OK", res
    req = r.sent(system)[0]
    validate_request(req.as_dict(), strict_cap=True)                      # never a root cap; correlation == rid#idx
    cav = dict(extcap.caveats_of(req.cap)[2:])                            # after the root step (system, deployment)
    payload = req.payload
    assert cav == {"system": system, "operation": eop, "target": target, "payload_digest": payload_digest(payload),
                   "correlation": correlation("c1", 0), "max_uses": uses, "not_after_tick": r.clock.now() + r.binding.window}
    assert [n for n, _ in extcap.caveats_of(req.cap)[:2]] == ["system", "deployment"]
    assert (req.request_id, req.effect_index, req.system, req.operation, req.target) == ("c1", 0, system, eop, target)


def test_r28_13_no_root_cap_ever_reaches_an_adapter(tmp_path):
    r = make_g4(tmp_path)
    for i, (who, op, args) in enumerate([("planner-1", "transfer_inventory", TRANSFER), ("planner-1", "expedite_purchase_order", EXPEDITE),
                                         ("planner-1", "reschedule_work_order", RESCHEDULE)]):
        r.dep.call_tool(r.token(who), op, args, request_id=f"r{i}")
    roots = set(r.binding.root_caps.values())
    sent = [q for s in r.recorders.values() for q in s.log]
    assert len(sent) == 3 and not [q for q in sent if q.cap in roots or extcap.chain_id(q.cap) == ""]


def test_r28_8_resubmission_reuses_the_same_cap_and_never_double_applies(tmp_path):
    r = make_g4(tmp_path, default=TimeoutAfterApply)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="t1")
    assert r.dep.dispatch_pending().body["submitted"] >= 1                 # the reply was lost: allowed to resubmit
    caps = {q.cap for q in r.sent("ERP")}
    assert len(r.sent("ERP")) >= 2 and len(caps) == 1                     # same chain, never a second cap
    assert len(r.ledger()) == 1                                           # at_most_once: one applied row
    assert {a["reason"] for a in r.ledger("audit") if a["outcome"] == "refused"} == {"uses_exhausted"}
    assert r.dep.reconcile("t1", r.clock.now()).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"


def test_r28_8_attempts_are_bounded(tmp_path):
    r = make_g4(tmp_path, default=Omit)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="b1")
    for _ in range(6):
        r.dep.dispatch_pending()
    assert len(r.sent("ERP")) == 3 and len({q.cap for q in r.sent("ERP")}) == 1


def test_r28_7_duplicate_delivery_by_adapter_is_stopped_by_max_uses(tmp_path):
    r = make_g4(tmp_path, default=Dup)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="d1")
    assert len(r.ledger()) == 1


def test_r28_7_idempotent_set_allows_up_to_three_harmless_applications(tmp_path):
    r = make_g4(tmp_path, default=Dup)
    r.dep.call_tool(r.token("planner-1"), "reschedule_work_order", RESCHEDULE, request_id="d2")
    assert len(r.ledger()) == 3
    o = r.dep.reconcile("d2", r.clock.now()).body["outcomes"][0]
    assert o["state"] == "RECONCILED_SUCCESS"


def test_r28_8_replayed_request_id_never_dispatches_again(tmp_path):
    r = make_g4(tmp_path)
    first = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="p1")
    again = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="p1")
    assert again.body["replayed"] is True and again.body["outcomes"] and len(r.sent("ERP")) == 1 and len(r.ledger()) == 1
    assert r.dep.dispatch_pending().body == {"submitted": 0}


def test_c28_6_crash_after_commit_then_restart_resubmits_with_the_same_cap(tmp_path):
    r = make_g4(tmp_path)
    r.dep.arm_crash("after_commit")
    res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="x1")
    assert (res.status, res.body["reason"]) == ("UNKNOWN", "crashed") and r.sent("ERP") == [] and r.ledger() == []
    assert r.dep.dispatch_pending().status == "UNAVAILABLE"
    r.dep.restart()
    assert r.dep.outcome("x1").body["outcomes"][0]["state"] == "PENDING"      # the intent survived the crash
    assert r.dep.dispatch_pending().body == {"submitted": 1}
    assert len({q.cap for q in r.sent("ERP")}) == 1 and len(r.ledger()) == 1
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="x1")   # client retry: a replay
    assert len(r.sent("ERP")) == 1 and r.dep.dispatch_pending().body == {"submitted": 0}
    assert r.dep.reconcile("x1", r.clock.now()).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"


def test_c28_6_crash_before_commit_leaves_no_intent(tmp_path):
    r = make_g4(tmp_path)
    r.dep.arm_crash("before_commit")
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="x2")
    r.dep.restart()
    assert r.dep.dispatch_pending().body == {"submitted": 0} and r.dep.outcome("x2").status == "INVALID"


def test_concurrent_requests_and_dispatch_never_double_apply(tmp_path):
    import threading
    r = make_g4(tmp_path)
    errs = []

    def go(i):
        try:
            for _ in range(2):   # same request_id twice: one commit, one replay
                r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id=f"th{i}")
            r.dep.dispatch_pending()
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    corr = [e["correlation"] for e in r.ledger()]
    assert sorted(corr) == sorted(f"th{i}#0" for i in range(6)) == sorted(set(corr))
