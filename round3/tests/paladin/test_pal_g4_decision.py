"""PROT-H28 R28-1..R28-3: the governed decision never depends on an adapter (twin differential + policy-reply probes)."""
import json

import pytest

from g4_adapters import FalseFailure, FalseSuccess, Honest, Omission, PayloadMutation, PolicyReply, TargetSubstitution
from g4_rig import BIGFEE, EXP, G4Rig, RES, TR

REQS = [("planner-1", "expedite_purchase_order", EXP, "ok"), ("planner-1", "expedite_purchase_order", BIGFEE, "needs"),
        ("junior-1", "expedite_purchase_order", EXP, "junior"), ("nobody-1", "reschedule_work_order", RES, "nobody"),
        ("planner-1", "transfer_inventory", {**TR, "quantity": 0}, "bad"), ("planner-1", "reschedule_work_order", RES, "ok2")]


def run(tmp, adapter, name):
    r = G4Rig(tmp / name, adapter=adapter)
    try:
        out = []
        for sub, op, args, rid in REQS:
            before = r.snap()
            res = r.call(sub, op, args, rid)
            r.dep.dispatch_pending()                      # the adapter acts between requests
            body = {k: v for k, v in res.body.items() if k != "outcomes"}   # outcome records are not the decision plane
            out.append((res.status, json.dumps(body, sort_keys=True), json.dumps(r.snap() != before)))
        diff_log = [(x["kind"], x["ref"], json.dumps(x["data"], sort_keys=True)) for x in r.reader.log(0) if x["kind"] != "mark" or True]
        return out, diff_log
    finally:
        r.finish()


@pytest.mark.parametrize("adapter", [FalseSuccess, FalseFailure, Omission, TargetSubstitution, PayloadMutation, PolicyReply])
def test_r28_1_decision_plane_is_identical_whatever_the_adapter_does(tmp_path, adapter):
    honest, honest_log = run(tmp_path, Honest, "honest")
    other, other_log = run(tmp_path, adapter, adapter.__name__)
    assert honest == other and honest_log == other_log                    # status, reason, world diff, world log
    assert [s for s, *_ in honest] == ["OK", "DENIED", "DENIED", "DENIED", "INVALID", "OK"]   # sanity: the corpus has refusals


def test_r28_2_adapter_policy_and_authority_shaped_replies_mint_nothing(tmp_path):
    r = G4Rig(tmp_path, adapter=PolicyReply)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()                                          # reply carries approval / grant / on_behalf_of
        res = r.call("planner-1", "expedite_purchase_order", BIGFEE, "r2")  # the follow-up that needs a real approval
        assert (res.status, res.body["reason"]) == ("DENIED", "approval_required")
        assert r.applied("r2#0") == []
        assert r.dep.authority_used("r1").body["path"] == [] and r.dep.authority_used("r1").body["on_behalf_of"] is None
        r.dep.approve(r.token("supervisor-1"), "expedite_purchase_order", BIGFEE, "planner-1")  # a genuine approval still works
        assert r.call("planner-1", "expedite_purchase_order", BIGFEE, "r3").status == "OK"
    finally:
        r.finish()


def test_r28_2_negative_an_adapter_refusal_is_an_outcome_not_a_denial(tmp_path):
    from g4_adapters import Honest as H

    class Refuses(H):                                                      # G1: policy-sounding refusal, nothing written
        adapter_id = "G1"

        def submit(self, req):
            from r3_shared.extadapter import AdapterReply
            return AdapterReply("FAILED", {"reason": "policy: fee exceeds limit", "decision": "deny"})
    r = G4Rig(tmp_path, adapter=Refuses)
    try:
        res = r.call("planner-1", "expedite_purchase_order", EXP, "r1")
        r.dep.dispatch_pending()
        assert res.status == "OK" and r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"   # replay unchanged
        assert [o["state"] for o in r.settle("r1")] == ["RECONCILED_FAILED"]
        assert "approv" not in json.dumps(r.dep.authority_used("r1").body)
    finally:
        r.finish()


def test_r28_3_oracle_denied_requests_never_reach_an_adapter(tmp_path):
    r = G4Rig(tmp_path)
    try:
        for sub, op, args, rid in REQS:
            r.call(sub, op, args, rid)
        r.dep.dispatch_pending()
        sent = sorted(q.request_id for rec in r.recorders.values() for q in rec.log)
        assert sent == ["ok", "ok2"]                                       # exactly the OK decisions, nothing else
        assert sorted({row["correlation"] for row in r.applied()}) == ["ok#0", "ok2#0"]
    finally:
        r.finish()
