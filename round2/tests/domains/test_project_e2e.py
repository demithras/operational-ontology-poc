"""Project Ontology on the unchanged Engine: governed lifecycle over Git (in-memory git_change adapter).

``git_change`` effects land in the Git fake, not in the Engine store; the next step boots a fresh Engine on the
projection rebuilt from Git (``next_engine``). Every negative path asserts zero effects (store, EffectLog, Git)."""
from __future__ import annotations

import copy

import pytest

from prj_helpers import (EVIDENCE_002, Snap, drop_link, failed_gates, gate, ir_without_preconditions, make, next_engine,
                         prop, seed)

R1 = "researcher-1"


def _draft_h16(s):
    prop(s, "Hypothesis", "H16", phase="DRAFT", freeze_hash=None)


def _attach_all(e, git):
    for i, ev in enumerate(EVIDENCE_002):
        assert e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, R1,
                         idempotency_key=f"att{i}")["state"] == "RECONCILED_SUCCESS"


def _row(git, target, **match):
    return next(c["row"] for c in git.commits if c["target"] == target and all(c["row"].get(k) == v for k, v in match.items()))


def _hyp(e, hid):
    return e.get("Hypothesis", hid)["props"]


# ---- preregister -------------------------------------------------------------------------------
def test_preregister_complete_contract_writes_git_and_projection():
    e, git, _, sd = make(mutator=_draft_h16)
    fh = e.call_function("compute_freeze_hash", {"experiment": "exp-h16-001"})
    rec = e.propose("preregister_hypothesis", {"hypothesis": "H16", "freeze_hash": fh}, R1, idempotency_key="p1")
    assert rec["state"] == "RECONCILED_SUCCESS" and rec["soft_flags"][0]["constraint"]
    assert _row(git, "Hypothesis", **{"$key": "H16"}) == {"phase": "PREREGISTERED", "freeze_hash": fh, "$key": "H16"}
    assert _hyp(e, "H16")["phase"] == "DRAFT"  # Git is canonical; the store is only a projection
    e2 = next_engine(sd, git)
    assert _hyp(e2, "H16")["phase"] == "PREREGISTERED" and _hyp(e2, "H16")["freeze_hash"] == fh


@pytest.mark.parametrize("link", ["HAS_RIVAL", "PREDICTS", "FALSIFIED_BY"])
def test_preregister_incomplete_contract_denied_zero_effects(link):
    def mut(s):
        _draft_h16(s)
        drop_link(s, link, "H16")
    e, git, _, _ = make(mutator=mut)
    z = Snap(e, git)
    rec = e.propose("preregister_hypothesis", {"hypothesis": "H16", "freeze_hash": "abc"}, R1, idempotency_key="p")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"]
    assert "preregistration_requires_complete_contract" in str(gate(rec, "policy")["detail"]) and z.unchanged()


def test_preregister_needs_a_freeze_hash_and_a_draft_hypothesis():
    e, git, _, _ = make(mutator=_draft_h16)
    z = Snap(e, git)
    rec = e.propose("preregister_hypothesis", {"hypothesis": "H16", "freeze_hash": "  "}, R1, idempotency_key="p")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()
    e, git, _, _ = make()  # H17 is already PREREGISTERED
    rec = e.propose("preregister_hypothesis", {"hypothesis": "H17", "freeze_hash": "abc"}, R1, idempotency_key="p")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and not git.commits


# ---- thresholds ---------------------------------------------------------------------------------
def test_edit_threshold_after_preregistration_denied_zero_effects():
    e, git, _, _ = make()
    z = Snap(e, git)
    rec = e.propose("edit_threshold", {"threshold": "H17.min_state_machine_examples", "value": 1}, R1, idempotency_key="t")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()
    # the POLICY alone (preconditions removed from the action) denies it too: it is its own binding
    e, git, _, _ = make(package=ir_without_preconditions("edit_threshold"))
    z = Snap(e, git)
    rec = e.propose("edit_threshold", {"threshold": "H17.min_state_machine_examples", "value": 1}, R1, idempotency_key="t")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"]
    assert "threshold_edit_after_preregistration_denied" in str(gate(rec, "policy")["detail"]) and z.unchanged()


def test_edit_threshold_in_draft_succeeds_and_is_projected():
    e, git, _, sd = make(mutator=_draft_h16)
    rec = e.propose("edit_threshold", {"threshold": "H16.min_generated_mixed_cases", "value": 3000}, R1, idempotency_key="t")
    assert rec["state"] == "RECONCILED_SUCCESS"
    assert e.get("Threshold", "H16.min_generated_mixed_cases")["props"]["value"] == 2000
    assert next_engine(sd, git).get("Threshold", "H16.min_generated_mixed_cases")["props"]["value"] == 3000


# ---- start run ----------------------------------------------------------------------------------
def test_start_run_without_freeze_hash_denied_zero_effects():
    e, git, _, _ = make(mutator=lambda s: prop(s, "Hypothesis", "H16", freeze_hash=None))
    z = Snap(e, git)
    rec = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()
    e, git, _, _ = make(mutator=lambda s: prop(s, "Hypothesis", "H16", freeze_hash=None),
                        package=ir_without_preconditions("start_run"))
    z = Snap(e, git)
    rec = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"]
    assert "running_requires_freeze_hash" in str(gate(rec, "policy")["detail"]) and z.unchanged()


def test_start_run_with_freeze_hash_succeeds_and_illegal_transitions_are_denied():
    e, git, _, sd = make()
    assert e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")["state"] == "RECONCILED_SUCCESS"
    e2 = next_engine(sd, git)
    assert _hyp(e2, "H16")["phase"] == "RUNNING"
    z = Snap(e2, git)
    for hid in ("H16", "H15"):  # already RUNNING / already EVALUATED: not PREREGISTERED
        rec = e2.propose("start_run", {"hypothesis": hid}, R1, idempotency_key=f"again-{hid}")
        assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"]
    assert z.unchanged()
    # the reference lifecycle model itself rejects the jump (function is_legal_transition -> src/hdd reference model)
    assert e2.call_function("is_legal_transition", {"hypothesis": "H17", "target_phase": "RUNNING"}) is True
    assert e2.call_function("is_legal_transition", {"hypothesis": "H17", "target_phase": "EVALUATED"}) is False
    assert e2.call_function("is_legal_transition", {"hypothesis": "H15", "target_phase": "RUNNING"}) is False


# ---- evidence -----------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [("git_commit", ""), ("environment", " "), ("payload_hash", ""),
                                         ("experiment_version", "99")])
def test_attach_evidence_without_pin_denied_zero_effects(field, value):
    ev = EVIDENCE_002[0]
    e, git, _, _ = make("RUNNING", mutator=lambda s: prop(s, "Evidence", ev, **{field: value}))
    z = Snap(e, git)
    rec = e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, R1, idempotency_key="a")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()


def test_attach_evidence_policy_alone_denies_unpinned_evidence():
    ev = EVIDENCE_002[0]
    e, git, _, _ = make("RUNNING", mutator=lambda s: prop(s, "Evidence", ev, git_commit=""),
                        package=ir_without_preconditions("attach_evidence"))
    z = Snap(e, git)
    rec = e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, R1, idempotency_key="a")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"] and z.unchanged()
    assert "evidence_must_bind_version_commit_environment" in str(gate(rec, "policy")["detail"])


def test_attach_evidence_requires_running_phase():
    e, git, _, _ = make("EVALUATED")
    z = Snap(e, git)
    rec = e.propose("attach_evidence", {"hypothesis": "H15", "evidence": EVIDENCE_002[0]}, R1, idempotency_key="a")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()
