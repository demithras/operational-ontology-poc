"""P1f protocol, end to end against the FAKE deployment (real ExternalWorld process, real caps, real observer): decide-before-
dispatch outbox, observer-only outcomes, same-cap resubmission, observability classes, observer faults, crash after commit."""
import pytest
from r3_shared import extcap
from r3_shared.extobs import ObserverFault
from r3_shared.outcome import allowed_transition, validate_outcomes
from r3_shared.variant import Deployment, g4_call
from tests.fakes.ext_rig import FalseSuccess, Honest, Rig, TargetSubstitution, TimeoutAfterApply

ERP = [{"system": "ERP", "operation": "expedite", "payload": {"po_id": "PO-1", "expedite_fee": 10}}]
MES = [{"system": "MES", "operation": "reschedule", "payload": {"work_order_id": "WO-1", "new_planned_start": 7}}]
GEN = [{"system": "GEN-NULL", "operation": "record", "payload": {"key": "k"}}]


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    if r.proc.proc.poll() is None:
        r.finish()


def states(res):
    assert res.status == "OK", res
    return [(o["state"], o["confidence"]) for o in validate_outcomes(res.body)]


def settle(r, rid, extra=10):
    r.dep.dispatch_pending()
    r.tick(extra)
    return r.dep.reconcile(rid, r.clock.now())


def test_fake_deployment_has_the_g4_surface(rig):
    assert isinstance(rig.dep, Deployment)
    assert all(callable(getattr(rig.dep, m)) for m in ("dispatch_pending", "reconcile", "outcome"))
    assert g4_call(rig.dep, "outcome", "nope").status == "INVALID"
    with pytest.raises(ValueError):
        g4_call(rig.dep, "approve")


def test_honest_path_decide_commit_then_dispatch_then_observer_confirms(rig):
    rig.tick()
    res = rig.put("r1", ERP)
    assert res.status == "OK" and states(res) == [("PENDING", "full")]        # decision final; outcome pending
    assert rig.store.handle_factory()("probe").external_effects() == []        # external given: zero in-transaction writes
    assert len(rig.recorders["ERP"].log) == 0                                  # nothing dispatched before dispatch_pending
    assert rig.dep.dispatch_pending().body == {"submitted": 1}
    assert rig.dep.dispatch_pending().body == {"submitted": 0}                 # nothing left
    req = rig.recorders["ERP"].log[0]
    cav = dict((n, v) for n, v in extcap.caveats_of(req.cap)[2:])
    assert cav["correlation"] == "r1#0" and cav["max_uses"] == 1 and cav["not_after_tick"] == 1 + rig.systems["window"]
    assert cav["target"] == "po:PO-1" and extcap.chain_id(req.cap)
    r = rig.dep.reconcile("r1", rig.clock.now())
    assert states(r) == [("RECONCILED_SUCCESS", "full")] and r.body["outcomes"][0]["evidence"]
    assert rig.dep.outcome("r1").body == r.body                                # self-report equals the last reconcile
    out = rig.finish()
    assert out["head"]["effects"] == 1


def test_adapter_lie_never_becomes_success(tmp_path):
    r = Rig(tmp_path, adapter_cls=FalseSuccess)
    try:
        r.tick()
        r.put("r1", ERP)
        r.dep.dispatch_pending()
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("PENDING", "full")]         # window still open
        assert states(settle(r, "r1")) == [("RECONCILED_FAILED", "full")]                  # the "OK" reply is a hint only
    finally:
        r.finish()


def test_target_substitution_is_diverged_on_a_full_system(tmp_path):
    r = Rig(tmp_path, adapter_cls=TargetSubstitution)
    try:
        r.tick()
        r.put("r1", ERP)
        assert states(settle(r, "r1")) == [("DIVERGED", "full")]
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("DIVERGED", "full")]      # absorbing
    finally:
        out = r.finish()
    assert out["head"]["effects"] == 0


def test_timeout_after_apply_resubmits_with_same_cap_and_ledger_has_one_row(tmp_path):
    r = Rig(tmp_path, adapter_cls=TimeoutAfterApply)
    try:
        r.tick()
        r.put("r1", ERP)
        assert r.dep.dispatch_pending().body == {"submitted": 1}
        assert r.dep.dispatch_pending().body == {"submitted": 1}                           # R28-8: resubmission, same cap
        caps = {q.cap for q in r.recorders["ERP"].log}
        assert len(r.recorders["ERP"].log) == 2 and len(caps) == 1
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("RECONCILED_SUCCESS", "full")]
    finally:
        out = r.finish()
    assert out["head"] == {"effects": 1, "audit": 2}                                       # applied + benign uses_exhausted refusal


def test_effects_only_and_none_classes_are_lower_confidence(tmp_path):
    r = Rig(tmp_path)
    try:
        r.tick()
        r.put("r1", MES)
        r.put("r2", GEN, key="P2")
        assert states(r.dep.outcome("r2")) == [("UNKNOWN", "low")]
        s = settle(r, "r1")
        assert states(s) == [("RECONCILED_SUCCESS", "low")]
        assert states(r.dep.reconcile("r2", r.clock.now())) == [("UNKNOWN", "low")]       # stop rule: UNKNOWN for ever
        r.tick(50)
        assert states(r.dep.reconcile("r2", r.clock.now())) == [("UNKNOWN", "low")]
    finally:
        r.finish()


def test_substitution_on_effects_only_system_is_invisible(tmp_path):
    r = Rig(tmp_path, per_system={"MES": TargetSubstitution})
    try:
        r.tick()
        r.put("r1", MES)
        assert states(settle(r, "r1")) == [("RECONCILED_FAILED", "low")]   # the refused write left no visible audit row (L2)
    finally:
        r.finish()


def test_observer_unavailable_keeps_final_states_and_unknowns_the_rest(tmp_path):
    r = Rig(tmp_path, fault=ObserverFault.unavailable(reads={1}))
    try:
        r.tick()
        r.put("r1", ERP)
        r.dep.dispatch_pending()
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("RECONCILED_SUCCESS", "full")]   # read 0
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("RECONCILED_SUCCESS", "full")]   # read 1 unavailable: rule U keeps P
    finally:
        r.finish()


def test_observer_unavailable_before_any_success_is_unknown(tmp_path):
    r = Rig(tmp_path, fault=ObserverFault.unavailable())
    try:
        r.tick()
        r.put("r1", ERP)
        r.dep.dispatch_pending()
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("UNKNOWN", "full")]
        assert r.dep.reconcile("nope", 1).status == "INVALID"
    finally:
        r.finish()


def test_lagging_observer_holds_pending_until_complete(tmp_path):
    r = Rig(tmp_path, fault=ObserverFault.lagging(3))
    try:
        r.tick()
        r.put("r1", ERP)
        r.dep.dispatch_pending()
        r.tick(1)                                                      # now 2: ct = -1, the row (tick 1) is withheld
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("PENDING", "full")]
        r.tick(7)                                                      # now 9: ct = 6 <= E(9): still not failed, row visible
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("RECONCILED_SUCCESS", "full")]
        assert allowed_transition("PENDING", "RECONCILED_SUCCESS")
    finally:
        r.finish()


def test_crash_after_commit_then_restart_resubmits_same_cap(tmp_path):
    r = Rig(tmp_path)
    try:
        r.tick()
        r.dep.arm_crash("after_commit")
        assert r.put("r1", ERP).status == "UNKNOWN"
        assert r.dep.dispatch_pending().status == "UNAVAILABLE"
        r.dep.crash()
        r.dep.restart()
        assert r.dep.dispatch_pending().body == {"submitted": 1}        # intent was durable (state_dir) before the crash
        assert r.put("r1", ERP).body.get("replayed")                     # replayed request_id never dispatches again
        assert r.dep.dispatch_pending().body == {"submitted": 0}
        assert states(r.dep.reconcile("r1", r.clock.now())) == [("RECONCILED_SUCCESS", "full")]
    finally:
        out = r.finish()
    assert out["head"]["effects"] == 1


def test_legacy_path_unchanged_when_external_is_none(tmp_path):
    r = Rig(tmp_path)
    try:
        dep = r.deploy(external=False)
        dep.call_tool(r.tok, "put", {"type": "Part", "key": "P9", "ext": ERP}, request_id="legacy-1")
        eff = r.store.handle_factory()("probe").external_effects()
        assert [(e["adapter"], e["target"]) for e in eff] == [("ERP", "expedite")]            # in-transaction external_write
        assert dep.dispatch_pending().body == {"submitted": 0} and dep.outcome("legacy-1").status == "INVALID"
        assert len(r.recorders["ERP"].log) == 0
    finally:
        r.finish()
