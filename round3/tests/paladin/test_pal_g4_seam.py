"""Gate 4 seam (PROT-H28 R28-1, R28-9, R28-13; conformance C28-1/C28-3): with `external` given nothing is written to the world's
external_effects table, every external effect goes through the harness adapter AFTER the world commit with a per-effect cap and
the byte-exact decision envelope; external=None keeps the legacy in-transaction path."""
import json

from g4_rig import BIGFEE, EXP, G4Rig, RES, TR
from r3_shared import extcap
from r3_shared.extadapter import canon_json, correlation, payload_digest, validate_request


def test_external_given_writes_no_world_external_effect_and_no_submit_before_dispatch(tmp_path):
    r = G4Rig(tmp_path)
    try:
        res, eff = r.effects_of(lambda: r.call("planner-1", "expedite_purchase_order", EXP, "r1"))
        assert res.status == "OK", res
        assert [e for e in eff if e["kind"] == "external"] == []                  # no WorldHandle.external_write
        assert all(len(rec.log) == 0 for rec in r.recorders.values()) and r.ledger()["effects"] == []   # nothing submitted yet
        assert [o["state"] for o in res.body["outcomes"]] == ["PENDING"]
        assert r.dep.dispatch_pending().body == {"submitted": 1}
        assert len(r.recorders["ERP"].log) == 1 and len(r.applied()) == 1
    finally:
        r.finish()


def test_negative_legacy_path_unchanged_with_external_none(tmp_path):
    r = G4Rig(tmp_path)
    try:
        dep = r.deploy(external=None)
        res, eff = r.effects_of(lambda: dep.direct(r.token("planner-1"), "expedite_purchase_order", EXP, request_id="leg-1"))
        assert res.status == "OK" and [e["kind"] for e in eff] == ["external"] and "outcomes" not in res.body
        assert r.ledger()["effects"] == [] and dep.dispatch_pending().body == {"submitted": 0}
        assert dep.reconcile("leg-1", 5).status == "INVALID" and dep.outcome("leg-1").body == {"reason": "unknown_request"}
    finally:
        r.finish()


def test_cap_carries_exactly_the_r28_13_caveats_and_never_the_root(tmp_path):
    r = G4Rig(tmp_path)
    try:
        for rid, op, args in (("a", "expedite_purchase_order", EXP), ("b", "transfer_inventory", TR),
                              ("c", "reschedule_work_order", RES)):
            assert r.call("planner-1", op, args, rid).status == "OK"
        r.dep.dispatch_pending()
        want = {"a": ("ERP", "expedite", "po:PO-992", EXP, 1), "c": ("MES", "reschedule", "wo:WO-43", RES, 3),
                "b": ("WMS", "transfer", "transfer:PX-900@WH-C->WH-B",
                      {"source": "WH-C", "destination": "WH-B", "part": "PX-900", "quantity": 60}, 1)}
        for rid, (sysn, op, target, payload, uses) in want.items():
            (req,) = r.recorders[sysn].log
            validate_request(req.as_dict(), strict_cap=True)                      # a per-effect cap, never a root cap
            cav = dict(extcap.caveats_of(req.cap)[2:])
            assert cav == {"system": sysn, "operation": op, "target": target, "payload_digest": payload_digest(payload),
                           "correlation": correlation(rid, 0), "max_uses": uses, "not_after_tick": 8}
            assert (req.system, req.operation, req.target, req.payload) == (sysn, op, target, payload)
            assert req.cap != r.binding.root_caps[sysn]
    finally:
        r.finish()


def test_envelope_text_is_the_auditors_byte_exact_decision_envelope(tmp_path):
    r = G4Rig(tmp_path, history=True)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        (req,) = r.recorders["ERP"].log
        rep = r.dep.replay("r1")
        assert rep.status == "VERIFIED" and req.envelope_text == canon_json(rep.envelope)
        assert json.loads(req.envelope_text)["decision"]["decision_id"] == "r1"
    finally:
        r.finish()


def test_negative_no_provable_envelope_no_dispatch(tmp_path):
    r = G4Rig(tmp_path, history=True)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.anchor.close()                                                         # anchor gone: the envelope cannot be proven
        assert r.dep.dispatch_pending().body == {"submitted": 0} and r.recorders["ERP"].log == []
    finally:
        r.proc.close()
