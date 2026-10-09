"""G4 fix round 1: E20 evidence values are DISTINCT (frozen validator accepts every outcome), E23 every non-crash request carries
the auditor's byte-exact envelope, E24/E22 stay with the shared code / harness."""
import pytest

from g4_rig import EXP, G4Rig, RES, TR
from paladin.extoutcome import outcome_state
from r3_shared.extadapter import canon_json
from r3_shared.extobs import AudRow, EffRow, ObsSnapshot
from r3_shared.outcome import validate_outcome

I = {"operation": "expedite", "target": "po:P", "payload_digest": "d" * 64, "correlation": "r#0", "expiry": 8,
     "idempotency": "at_most_once", "observability": "full"}
PEND = {"state": "PENDING", "confidence": "full", "evidence": []}


def _form(o):
    return validate_outcome({"request_id": "r", "effect_index": 0, "system": "ERP", **o})


def test_e20_coinciding_effect_and_audit_seq_appear_once():
    ef = lambda s, **k: EffRow(s, 1, "ERP", k.get("op", "expedite"), "po:P", "d" * 64, "c", "r#0", "a")  # noqa: E731
    au = lambda s: AudRow(s, 1, "ERP", "expedite", "po:P", "d" * 64, "c", "r#0", "a", "applied", "")  # noqa: E731
    o = outcome_state(I, ObsSnapshot(5, [ef(3)], [au(3)], 5), PEND)
    assert o["evidence"] == [3] and _form(o)["state"] == "RECONCILED_SUCCESS"          # [3, 3] would be rejected
    o = outcome_state(I, ObsSnapshot(5, [ef(2), ef(3)], [au(3), au(4)], 5), PEND)       # D3: partial overlap
    assert o["state"] == "DIVERGED" and o["evidence"] == [2, 3, 4] and _form(o)


def test_e20_live_outcomes_pass_the_frozen_validator(tmp_path):
    """Honest adapter on a full-observability system: effects.seq == audit.seq in the fresh world; every emitted outcome validates."""
    r = G4Rig(tmp_path)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        outs = r.settle("r1")
        led = r.ledger()
        assert {x["seq"] for x in led["effects"]} & {x["seq"] for x in led["audit"]}          # namespaces really coincide
        assert outs[0]["state"] == "RECONCILED_SUCCESS" and len(outs[0]["evidence"]) == len(set(outs[0]["evidence"]))
        for o in outs:
            validate_outcome(o)
    finally:
        r.finish()


@pytest.mark.parametrize("domain,op,args,sub", [("manufacturing", "expedite_purchase_order", EXP, "planner-1"),
                                               ("manufacturing", "transfer_inventory", TR, "planner-1")])
def test_e23_every_request_carries_its_decisions_auditor_envelope(tmp_path, domain, op, args, sub):
    r = G4Rig(tmp_path, domain=domain, history=True)
    try:
        for k in range(3):
            assert r.call(sub, op, args, f"r{k}").status == "OK", k
        r.dep.dispatch_pending()
        seen = [q for rec in r.recorders.values() for q in rec.log]
        assert len(seen) >= 3
        for q in seen:
            rep = r.dep.replay(q.request_id)
            assert rep.status == "VERIFIED" and q.envelope_text == canon_json(rep.envelope), q.request_id
    finally:
        r.finish()


def test_e23_negative_envelope_of_another_decision_differs(tmp_path):
    r = G4Rig(tmp_path, history=True)
    try:
        for k in range(2):
            assert r.call("planner-1", "expedite_purchase_order", EXP, f"r{k}").status == "OK"
        r.dep.dispatch_pending()
        a, b = (q for rec in r.recorders.values() for q in rec.log)
        assert a.envelope_text != b.envelope_text and a.envelope_text == canon_json(r.dep.replay(a.request_id).envelope)
        assert b.envelope_text != canon_json(r.dep.replay(a.request_id).envelope)
    finally:
        r.finish()
