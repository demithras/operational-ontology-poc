"""Lifecycle paths up to the gate decision. Every negative path: ZERO effects in EffectLog and store unchanged."""
import pytest

from eoo_engine import CapabilityError, Principal
from synth import build, effects_of


def _denied(eng, rec, gate, before_hash):
    assert rec["state"] == "DENIED", rec["state"]
    assert rec["gates"][-1]["gate"] == gate and rec["gates"][-1]["passed"] is False, rec["gates"]
    assert effects_of(eng, rec["exec"]) == ()
    assert eng.state().state_hash() == before_hash


def test_allowed_path_commits_one_effect_with_provenance():
    eng, _, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k1")
    assert rec["history"] == ["PROPOSED", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED", "RECONCILED_SUCCESS"]
    assert eng.get("Box", "b1")["props"]["level"] == 15
    assert len(effects_of(eng, rec["exec"])) == 1
    prov = eng.provenance.where(exec=rec["exec"])[-1]
    assert prov["package_id"] == "synthetic-boxes" and prov["package_version"] == "s1"
    assert prov["action"] == "fill_box" and prov["action_version"] == "a1"
    assert prov["policy_versions"] == {"p-deny": "pv1", "p-approval": "pv1", "p-allow": "pv2", "p-classify": "pv1"}
    assert prov["principal"]["pid"] == "filler" and prov["inputs"] == {"box": "b1", "amount": 5}
    assert [g["gate"] for g in prov["gates"]] == ["identity", "inputs", "authority", "preconditions", "policy",
                                                 "hard_constraints"]
    assert list(prov["effect_ids"]) == [f"{rec['exec']}/e0"] and prov["observed"]["verdict"] is True
    assert prov["updated_at"].startswith("t")


def test_authority_denied_no_rule():
    eng, _, _ = build()
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": 5}, "nobody", idempotency_key="k"), "authority", h)


def test_deny_rule_overrides_allow():
    eng, _, _ = build()
    h = eng.state().state_hash()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "blocked", idempotency_key="k")
    _denied(eng, rec, "authority", h)
    assert "blocked" in rec["gates"][-1]["detail"]["deny"] and "filler" in rec["gates"][-1]["detail"]["allow"]


@pytest.mark.parametrize("who", ["ghost", Principal("filler", {"filler", "approver"}), 42])
def test_identity_unknown_or_forged(who):
    eng, _, _ = build()
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": 5}, who, idempotency_key="k"), "identity", h)


def test_policy_denied():
    eng, k, _ = build()
    k["deny"] = True
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k"), "policy", h)


def test_default_deny_when_no_allow_policy_applies():
    eng, k, _ = build()
    k["allow"] = False
    h = eng.state().state_hash()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    _denied(eng, rec, "policy", h)
    assert rec["gates"][-1]["detail"]["default_deny"] is True


def test_classify_only_annotates():
    eng, k, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    assert rec["state"] == "RECONCILED_SUCCESS"
    assert [g for g in rec["gates"] if g["gate"] == "policy"][0]["detail"]["classified"] == ["p-classify"]


def test_precondition_failed():
    eng, _, _ = build()
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": -3}, "filler", idempotency_key="k"),
            "preconditions", h)


@pytest.mark.parametrize("bad", [lambda ctx: "yes", lambda ctx: 1 / 0])
def test_broken_precondition_logic_fails_closed(bad):
    eng, _, _ = build()
    eng.bindings.bind("precondition", "amount is positive", bad)
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": 3}, "filler", idempotency_key="k"),
            "preconditions", h)


@pytest.mark.parametrize("inputs", [{"box": "missing", "amount": 1}, {"box": "b1", "amount": "1"}, {"box": "b1"},
                                    {"box": "b1", "amount": 1, "extra": 1}, {"box": "s1", "amount": 1}])
def test_invalid_inputs(inputs):
    eng, _, _ = build()
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", inputs, "filler", idempotency_key="k"), "inputs", h)


def test_require_approval_then_approved():
    eng, _, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")
    assert rec["state"] == "PENDING_APPROVAL" and effects_of(eng, rec["exec"]) == ()
    assert eng.get("Box", "b1")["props"]["level"] == 10
    rec = eng.approve(rec["exec"], "approver")
    assert rec["state"] == "RECONCILED_SUCCESS" and eng.get("Box", "b1")["props"]["level"] == 70
    assert rec["approvals"][0]["pid"] == "approver" and rec["soft_flags"] == [{"constraint": "level-soft", "error": None}]


def test_require_approval_then_rejected():
    eng, _, _ = build()
    h = eng.state().state_hash()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")
    _denied(eng, eng.reject(rec["exec"], "approver"), "approval", h)


@pytest.mark.parametrize("approver", ["filler", "filler2", "ghost", Principal("approver", {"approver", "x"})])
def test_approval_needs_second_principal_with_capability(approver):
    eng, _, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")
    with pytest.raises(CapabilityError):
        eng.approve(rec["exec"], approver)
    assert rec["state"] == "PENDING_APPROVAL" and effects_of(eng, rec["exec"]) == ()
    assert eng.provenance.where(kind="attempt", exec=rec["exec"])


def test_relation_selector_and_delegation():
    eng, _, _ = build()
    assert eng.propose("fill_box", {"box": "b1", "amount": 1}, "keeper", idempotency_key="k1")["state"] == \
        "RECONCILED_SUCCESS"
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b2", "amount": 1}, "keeper", idempotency_key="k2"), "authority", h)
    # A delegate must itself match the selector, the rule must allow delegation, and the delegator must be
    # allowed under the same rule set: keeper-strict (delegation_allowed=false) does not carry over.
    rec = eng.propose("fill_box", {"box": "b1", "amount": 1}, "agent", idempotency_key="k3")
    assert rec["state"] == "RECONCILED_SUCCESS"
    d = [g for g in rec["gates"] if g["gate"] == "authority"][0]["detail"]
    assert d["allow"] == ["keeper-delegable"]
    h = eng.state().state_hash()
    _denied(eng, eng.propose("fill_box", {"box": "b1", "amount": 1}, "rogue-agent", idempotency_key="k4"),
            "authority", h)
