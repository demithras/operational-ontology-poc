"""Lifecycle paths from APPROVED on: constraints, idempotency, staleness, outcome, reconciliation."""
import pytest

from eoo_engine import LoadError, Unbound
from synth import FakeCarrier, bindings, build, effects_of, knobs, package
from eoo_engine import AdapterRegistry, Engine


def test_hard_constraint_blocks_before_commit():
    eng, _, _ = build()
    h = eng.state().state_hash()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 95}, "filler", idempotency_key="k")
    assert rec["state"] == "PENDING_APPROVAL"
    rec = eng.approve(rec["exec"], "approver")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "hard_constraints"
    assert rec["gates"][-1]["detail"] == [{"constraint": "level-cap", "error": None}]
    assert effects_of(eng, rec["exec"]) == () and eng.state().state_hash() == h


def test_constraint_scoped_to_other_action_is_not_evaluated():
    eng, k, _ = build()
    k["ship_constraint"] = False  # scoped to ship_box only
    assert eng.propose("fill_box", {"box": "b1", "amount": 1}, "filler", idempotency_key="k")["state"] == \
        "RECONCILED_SUCCESS"
    h = eng.state().state_hash()
    rec = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="s")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "hard_constraints"
    assert effects_of(eng, rec["exec"]) == () and eng.state().state_hash() == h


def test_idempotent_retry_same_result_no_second_effect():
    eng, _, carrier = build()
    a = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="same")
    b = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="same")
    # v1.1: returns are detached snapshots, so "same result" is equality of the snapshot, not object identity
    assert a == b and a is not b and a["exec"] == b["exec"] and a["state"] == "RECONCILED_SUCCESS"
    assert len(carrier.calls) == 1 and len(effects_of(eng, a["exec"])) == 1 and len(eng.effect_log) == 1
    assert eng.provenance.where(kind="retry", exec=a["exec"])


def test_idempotency_key_reuse_for_other_intent_is_denied():
    eng, _, carrier = build()
    eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="same")
    rec = eng.propose("ship_box", {"box": "b2"}, "filler", idempotency_key="same")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "idempotency"
    assert effects_of(eng, rec["exec"]) == () and len(carrier.calls) == 1


def test_missing_required_idempotency_key_is_denied():
    eng, _, carrier = build()
    rec = eng.propose("ship_box", {"box": "b1"}, "filler")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "request" and carrier.calls == []


def test_not_applicable_idempotency_runs_twice():
    eng, _, _ = build()
    assert eng.propose("make_box", {"key": "n1", "level": 1}, "filler")["state"] == "RECONCILED_SUCCESS"
    rec = eng.propose("make_box", {"key": "n1", "level": 1}, "filler")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "integrity"  # second create collides


def test_stale_base_after_pending_approval():
    eng, _, _ = build()
    slow = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="slow")
    fast = eng.propose("fill_box", {"box": "b1", "amount": 1}, "filler", idempotency_key="fast")
    assert fast["state"] == "RECONCILED_SUCCESS"
    h = eng.state().state_hash()
    rec = eng.approve(slow["exec"], "approver")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "stale"
    assert effects_of(eng, rec["exec"]) == () and eng.state().state_hash() == h


def test_expected_version_mismatch_at_proposal():
    eng, _, _ = build()
    h = eng.state().state_hash()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 1}, "filler", idempotency_key="k",
                      expected_versions={repr(("Box", "b1")): 7})
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "stale"
    assert effects_of(eng, rec["exec"]) == () and eng.state().state_hash() == h


def test_outcome_unknown_then_reconciled_later():
    eng, _, carrier = build(carrier=FakeCarrier("silent"))
    rec = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="k")
    assert rec["state"] == "OUTCOME_UNKNOWN" and len(effects_of(eng, rec["exec"])) == 1
    carrier.emit(rec["exec"], "DELIVERED", otype="NoSuchType")  # rejected: not an IR observation type
    assert eng.reconcile(rec["exec"])["state"] == "OUTCOME_UNKNOWN"
    rec = eng.executions[rec["exec"]]  # v1.1: read the updated record through the API (returns are snapshots)
    assert rec["rejected_observations"][0]["problems"] == ["unknown observation type 'NoSuchType'"]
    carrier.emit(rec["exec"], "DELIVERED")
    assert eng.reconcile(rec["exec"])["state"] == "RECONCILED_SUCCESS" and len(carrier.calls) == 1


def test_reconciliation_failure():
    eng, _, carrier = build(carrier=FakeCarrier("fail"))
    rec = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="k")
    assert rec["state"] == "RECONCILED_FAILED" and rec["observed"]["verdict"] is False
    assert len(effects_of(eng, rec["exec"])) == 1  # the effect happened; the observed outcome disagrees


def test_adapter_error_makes_outcome_unknown():
    eng, _, carrier = build(carrier=FakeCarrier("raise"))
    rec = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="k")
    assert rec["state"] == "OUTCOME_UNKNOWN" and rec["adapter_errors"] and len(carrier.calls) == 1


def test_unbound_logic_is_a_load_error_not_a_default():
    b = bindings(knobs())
    b._fns.pop(("policy", "expr:allow"))
    with pytest.raises(LoadError) as ei:
        Engine(package(), b, AdapterRegistry({("external_call", "Carrier"): FakeCarrier()}))
    assert Unbound("policy", "expr:allow", "policies.p-allow") in ei.value.problems
    with pytest.raises(LoadError) as ei:
        Engine(package(), bindings(knobs()), AdapterRegistry({}))
    assert [p.kind for p in ei.value.problems] == ["adapter"]


def test_invalid_ir_is_rejected():
    pkg = package()
    pkg["actions"][0]["authority_refs"].append("auth:nope")
    with pytest.raises(LoadError):
        Engine(pkg, bindings(knobs()), AdapterRegistry({("external_call", "Carrier"): FakeCarrier()}))
