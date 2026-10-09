"""G4 fix round 1: E19/E20 evidence ints, E16 monotone watermark, E17 anon correlation, E23 envelope byte-equality."""
import json
import sqlite3

from conv_g4_util import EXPEDITE, Dup, Honest, make_g4
from conventional import extrecon
from r3_shared import outcome as oc
from r3_shared.extobs import AudRow, EffRow, ObsSnapshot


def _eff(seq, corr="r#0"):
    return EffRow(seq, 3, "ERP", "expedite", "po:PO-1", "d1", "c", corr, "H0")


def _aud(seq, corr="r#0", **kw):
    return AudRow(seq, 3, "ERP", "expedite", "po:PO-1", "d1", "c", corr, "H0", "refused", "uses_exhausted")


I = {"operation": "expedite", "target": "po:PO-1", "payload_digest": "d1", "correlation": "r#0"}


def test_e20_evidence_is_sorted_distinct_ints_with_a_coinciding_seq():
    s = ObsSnapshot(5, [_eff(1), _eff(3)], [_aud(1), _aud(2), _aud(9, corr="other#0")], 5)
    st, _, ev = extrecon.outcome_state(I, s, "PENDING", "idempotent_set", "full", 8)
    assert ev == [1, 2, 3] and all(type(x) is int and x > 0 for x in ev)       # 1 present in both namespaces -> once
    _, _, ev_eo = extrecon.outcome_state(I, s, "PENDING", "idempotent_set", "effects_only", 8)
    assert ev_eo == [1, 3]                                                      # audit rows only when observability == full
    assert extrecon.outcome_state(I, s, "PENDING", "idempotent_set", "none", 8)[2] == []


def test_e20_public_outcome_evidence_end_to_end(tmp_path):
    r = make_g4(tmp_path, default=Dup)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="o1")
    assert [x["seq"] for x in r.ledger()] == [1] and [x["seq"] for x in r.ledger("audit")] == [1, 2, 3]
    r.tick(20)
    o = r.dep.reconcile("o1", r.clock.now()).body["outcomes"][0]
    assert o["evidence"] == [1, 2, 3]
    oc.validate_outcome(o)
    assert r.dep.outcome("o1").body["outcomes"][0]["evidence"] == [1, 2, 3]       # durable, same public form


def test_e16_lower_watermark_is_ignored_and_reconciled_never_returns_to_pending(tmp_path):
    r = make_g4(tmp_path)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="m1")
    r.tick(3)
    hi = r.dep.reconcile("m1", r.clock.now()).body["outcomes"][0]
    assert hi["state"] == "RECONCILED_SUCCESS" and hi["evidence"]
    lo = r.dep.reconcile("m1", 0).body["outcomes"][0]
    assert lo == hi


def test_e16_stale_watermark_does_not_regress_the_applied_watermark(tmp_path):
    r = make_g4(tmp_path, default=Honest)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="m2")
    r.tick(20)
    r.dep.reconcile("m2", r.clock.now())
    con = sqlite3.connect(r.tmp / "w.db")
    wm = con.execute("SELECT wm FROM conv_outcome WHERE request_id='m2'").fetchone()[0]
    assert wm == r.clock.now()
    r.dep.reconcile("m2", wm - 1)
    assert con.execute("SELECT wm FROM conv_outcome WHERE request_id='m2'").fetchone()[0] == wm
    con.close()


def test_e17_anon_correlation_is_world_seq_of_the_commit(tmp_path):
    r = make_g4(tmp_path)
    res = r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE)
    assert res.status == "OK"
    req = r.sent("ERP")[0]
    con = sqlite3.connect(r.tmp / "w.db")
    marks = [m[0] for m in con.execute("SELECT seq FROM world_log WHERE kind='mark' AND ref='commit' ORDER BY seq")]
    con.close()
    assert len(marks) == 1 and req.request_id == f"anon-tx{marks[0]}"           # the world_seq of THIS commit's mark
    seq = marks[0]
    assert r.ledger()[0]["correlation"] == f"anon-tx{seq}#0"
    assert r.dep.outcome(req.request_id).body["outcomes"][0]["state"] in ("PENDING", "RECONCILED_SUCCESS")


def test_e23_envelope_text_is_byte_equal_to_the_decision_envelope_for_every_request(tmp_path):
    r = make_g4(tmp_path, history=True)
    for rid in ("v1", "v2"):
        assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id=rid).status == "OK"
    for req in r.sent("ERP"):
        seq = r.dep.service.anchor.lookup(r.dep.service.stream, req.request_id)["seq"]
        assert req.envelope_text.encode() == r.hist.get(f"env/{seq:010d}") and req.envelope_text
        assert json.loads(req.envelope_text)["decision"]["decision_id"] == req.request_id


def test_injected_gen_null_operation_gets_a_typed_model_and_commits(tmp_path):
    """G4-E3/E22: the harness injects ONE unobservable-system operation into the deployed ops/auth specs."""
    import copy
    from conventional.models_gen import OPERATION_MODELS
    from conventional.models_dyn import ensure_models
    ops = {"operations": [{"name": "record", "inputs": [{"name": "key", "required": True, "type": "string"}],
                           "gated_inputs": ["key"], "approval": None}]}
    OPERATION_MODELS.pop("record", None)
    ensure_models(copy.deepcopy(ops))
    m = OPERATION_MODELS["record"]
    assert m.from_args({"key": "k1"}).inputs() == {"key": "k1"} and m.RESOURCES == {} and m.GATED == ("key",)
    import pytest
    from conventional.validation import RequestInvalid
    with pytest.raises(RequestInvalid):
        m.from_args({"key": "k1", "extra": 1})
    with pytest.raises(RequestInvalid):
        m.from_args({})
    OPERATION_MODELS.pop("record")


def test_commit_tick_comes_from_the_service_clock_not_the_world_store(tmp_path):
    r = make_g4(tmp_path)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="t1")
    con = sqlite3.connect(r.tmp / "w.db")
    tick, exp = con.execute("SELECT commit_tick, expiry FROM conv_outbox WHERE request_id='t1'").fetchone()
    con.close()
    assert tick == r.clock.now() and exp == tick + 8
