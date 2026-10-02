"""Project Ontology: evaluate (verdict derived by function), supersede, orphan flagging, decisions, idempotency, faults."""
from __future__ import annotations

import pytest

from domains.project.logic.freeze import freeze_digest
from hdd.verdict import CommonEvaluation, evaluate_common
from prj_helpers import (EVIDENCE_002, Snap, base_seed, drop_link, failed_gates, gate, ir_without_preconditions, make,
                         next_engine, prop, seed)

R1 = "researcher-1"


def _attach(e, ids, tag="a"):
    for i, ev in enumerate(ids):
        assert e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, R1,
                         idempotency_key=f"{tag}{i}")["state"] == "RECONCILED_SUCCESS"


def _verdict_row(git):
    return next(c["row"] for c in git.commits if c["target"] == "Verdict")


def test_evaluate_derives_the_verdict_by_function_not_by_input():
    e, git, _, sd = make("RUNNING")
    _attach(e, EVIDENCE_002)
    e2 = next_engine(sd, git)
    derived = e2.call_function("derive_verdict", {"hypothesis": "H15"})
    assert derived == "SUPPORTED"
    # independent check: the five booleans of the real evaluator fed to src/hdd/verdict.py give the same value
    common = {"protocol_valid": True, "required_evidence_complete": True, "sample_sufficient": True,
              "reject_hit": False, "support_hit": True}
    assert evaluate_common(CommonEvaluation(**common)).value == derived
    rec = e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")
    assert rec["state"] == "RECONCILED_SUCCESS" and rec["inputs"] == {"hypothesis": "H15"}
    row = _verdict_row(git)
    assert row["value"] == derived and row["derivation_hash"] and "machine-derived" in row["reason"]
    assert next(c["row"] for c in git.commits if c["target"] == "Hypothesis" and c["row"].get("phase") == "EVALUATED")
    e3 = next_engine(sd, git)
    assert e3.get("Hypothesis", "H15")["props"]["phase"] == "EVALUATED"
    assert e3.call_function("derive_verdict", {"hypothesis": "H15"}) == "SUPPORTED"


def test_a_verdict_cannot_be_supplied_as_input():
    e, git, _, _ = make("RUNNING")
    _attach(e, EVIDENCE_002)
    z = Snap(e, git)
    rec = e.propose("evaluate_hypothesis", {"hypothesis": "H15", "verdict": "SUPPORTED"}, R1, idempotency_key="ev")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["inputs"] and z.unchanged()


def test_missing_evidence_gives_inconclusive_never_supported():
    e, git, _, sd = make("RUNNING")
    _attach(e, EVIDENCE_002[:5])  # one required evidence file is missing
    e2 = next_engine(sd, git)
    assert e2.call_function("derive_verdict", {"hypothesis": "H15"}) == "INCONCLUSIVE"
    assert e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")["state"] == "RECONCILED_SUCCESS"
    assert _verdict_row(git)["value"] == "INCONCLUSIVE"


def test_tampered_evidence_hash_gives_invalid_verdict():
    """Known negative of the evaluator: the stored row no longer matches the committed record."""
    e, git, _, sd = make("RUNNING", mutator=lambda s: prop(s, "Evidence", EVIDENCE_002[0], payload_hash="0" * 64))
    _attach(e, EVIDENCE_002)
    e2 = next_engine(sd, git)
    assert e2.call_function("derive_verdict", {"hypothesis": "H15"}) == "INVALID"
    assert e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")["state"] == "RECONCILED_SUCCESS"
    assert _verdict_row(git)["value"] == "INVALID"


def _draft_no_supports(s):
    _drop_all_supports(s)
    prop(s, "Hypothesis", "H15", phase="DRAFT", freeze_hash=None)


def _drop_all_supports(s):
    for o in [o for o in s["ops"] if o["op"] == "create" and o["type"] == "Evidence"]:
        drop_link(s, "SUPPORTS_OR_REFUTES", o["key"])


def test_no_evidence_at_all_allows_only_an_inconclusive_verdict():
    e, git, _, _ = make("RUNNING")
    assert e.call_function("derive_verdict", {"hypothesis": "H15"}) == "INCONCLUSIVE"  # exp-h15-002: nothing attached
    e, git, _, _ = make("RUNNING", mutator=_drop_all_supports)
    assert e.call_function("evidence_count", {"hypothesis": "H15"}) == 0
    rec = e.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")
    assert rec["state"] == "RECONCILED_SUCCESS" and _verdict_row(git)["value"] == "INCONCLUSIVE"


def test_stored_verdict_that_differs_from_the_derived_one_blocks_everything():
    e, git, _, _ = make("EVALUATED", mutator=lambda s: prop(s, "Verdict", "verdict-H15-1", value="REJECTED"))
    z = Snap(e, git)
    rec = e.propose("flag_orphan_component", {"component": "cmp-legacy-draft"}, R1, idempotency_key="f")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["hard_constraints"] and z.unchanged()
    assert "verdict-machine-derived" in str(gate(rec, "hard_constraints")["detail"])


# ---- supersede ----------------------------------------------------------------------------------
def test_supersede_evaluated_hypothesis_links_successor_and_orphans_components():
    e, git, _, sd = make("EVALUATED")
    assert e.call_function("find_orphan_components", {}) == ("cmp-legacy-draft",)
    rec = e.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H16"}, R1, idempotency_key="s")
    assert rec["state"] == "RECONCILED_SUCCESS"
    e2 = next_engine(sd, git)
    assert e2.get("Hypothesis", "H15")["props"]["phase"] == "SUPERSEDED"
    assert [r["key"] for r in e2.read_view().follow("SUPERSEDED_BY", "Hypothesis", "H15", "out")] == ["H16"]
    assert set(e2.call_function("find_orphan_components", {})) == {"cmp-legacy-draft", "cmp-eoo-h15", "cmp-eoo-dsl"}
    # an orphan is FLAGGED, never deleted
    assert e2.propose("flag_orphan_component", {"component": "cmp-eoo-dsl"}, R1, idempotency_key="f")["state"] == "RECONCILED_SUCCESS"
    e3 = next_engine(sd, git)
    assert e3.get("Component", "cmp-eoo-dsl")["props"]["orphan_flagged"] is True and e3.get("Component", "cmp-eoo-ir")
    z = Snap(e3, git)
    rec = e3.propose("flag_orphan_component", {"component": "cmp-eoo-ir"}, R1, idempotency_key="f2")  # not an orphan
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()


def test_supersede_of_a_hypothesis_that_is_not_evaluated_is_denied_zero_effects():
    e, git, _, _ = make()
    z = Snap(e, git)
    rec = e.propose("supersede_hypothesis", {"hypothesis": "H16", "successor": "H17"}, R1, idempotency_key="s")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()


def test_FINDING_conflicting_change_policy_is_bound_but_no_action_references_it():
    """IR gap, reported not fixed: policy ``conflicting_change_denied_with_conflict`` (docs/05 explicit conflict) is in
    no action's policy_refs, so the Engine never evaluates it and superseding a hypothesis by itself is accepted.
    The binding itself is correct: once an action references it (test-only patched IR) the self-supersede is denied."""
    from domains._pack import load_ir
    import copy
    ir = load_ir("project")
    assert not [a["id"] for a in ir["actions"] if "policy:conflicting_change_denied_with_conflict" in a["policy_refs"]]
    e, git, _, _ = make()
    assert e.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H15"}, R1, idempotency_key="s")["state"] == "RECONCILED_SUCCESS"
    patched = copy.deepcopy(ir)
    for a in patched["actions"]:
        if a["id"] == "supersede_hypothesis":
            a["policy_refs"].append("policy:conflicting_change_denied_with_conflict")
    e, git, _, _ = make(package=patched)
    z = Snap(e, git)
    rec = e.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H15"}, R1, idempotency_key="s")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"] and z.unchanged()


def test_second_supersede_of_the_same_hypothesis_is_a_stale_write():
    e, git, _, sd = make()
    assert e.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H16"}, R1, idempotency_key="s")["state"] == "RECONCILED_SUCCESS"
    e2 = next_engine(sd, git)
    z = Snap(e2, git)
    rec = e2.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H17"}, R1, idempotency_key="s2")
    assert rec["state"] == "DENIED" and z.unchanged()


# ---- identity / authority / idempotency / decisions / versions ------------------------------------
@pytest.mark.parametrize("who,gate_name", [("viewer-1", "authority"), ("ghost", "identity")])
def test_unauthorized_or_unknown_principal_denied_zero_effects(who, gate_name):
    e, git, _, _ = make()
    z = Snap(e, git)
    rec = e.propose("start_run", {"hypothesis": "H16"}, who, idempotency_key="r")
    assert rec["state"] == "DENIED" and failed_gates(rec) == [gate_name] and z.unchanged()


def test_idempotent_retry_returns_the_same_execution_and_writes_git_once():
    e, git, _, _ = make()
    a = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="same")
    n = len(git.commits)
    b = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="same")
    assert a["exec"] == b["exec"] and b["state"] == "RECONCILED_SUCCESS" and len(git.commits) == n == 1
    clash = e.propose("start_run", {"hypothesis": "H17"}, R1, idempotency_key="same")
    assert clash["state"] == "DENIED" and len(git.commits) == 1
    miss = e.propose("start_run", {"hypothesis": "H18"}, R1)
    assert miss["state"] == "DENIED" and failed_gates(miss) == ["request"] and len(git.commits) == 1


def test_record_decision_pins_a_contract_version_and_needs_a_rationale():
    e, git, _, sd = make()
    rec = e.propose("record_decision", {"decision": "dec-h15-sidecar-option1", "contract_version": "cv-H15"}, R1, idempotency_key="d")
    assert rec["state"] == "RECONCILED_SUCCESS"
    e2 = next_engine(sd, git)
    assert [r["key"] for r in e2.read_view().follow("CHANGES", "Decision", "dec-h15-sidecar-option1", "out")] == ["cv-H15"]
    e, git, _, _ = make(mutator=lambda s: prop(s, "Decision", "dec-h15-sidecar-option1", rationale=" "))
    z = Snap(e, git)
    rec = e.propose("record_decision", {"decision": "dec-h15-sidecar-option1", "contract_version": "cv-H15"}, R1, idempotency_key="d")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()


def test_new_experiment_version_keeps_the_old_one_and_binds_a_new_contract_version():
    e, git, _, sd = make()
    rec = e.propose("new_experiment_version", {"experiment": "exp-h16-001", "contract_version": "cv-H16"}, R1, idempotency_key="n")
    assert rec["state"] == "RECONCILED_SUCCESS"
    e2 = next_engine(sd, git)
    old, new = e2.get("Experiment", "exp-h16-001")["props"], e2.get("Experiment", "exp-h16-001@v2")["props"]
    assert old["version"] == "1" and new["version"] == "2" and new["evaluator_ref"] == old["evaluator_ref"]
    cv = e2.get("ContractVersion", "cv-H16+2")["props"]
    assert cv["sha256"] == e2.call_function("compute_freeze_hash", {"experiment": "exp-h16-001"}) and cv["git_commit"] == sd["head_commit"]
    z = Snap(e2, git)  # the same new version again would overwrite history: refused
    rec = e2.propose("new_experiment_version", {"experiment": "exp-h16-001", "contract_version": "cv-H16"}, R1, idempotency_key="n2")
    assert rec["state"] == "DENIED" and z.unchanged()
    e3, git3, _, _ = make(mutator=lambda s: prop(s, "Hypothesis", "H16", phase="DRAFT", freeze_hash=None))
    rec = e3.propose("new_experiment_version", {"experiment": "exp-h16-001", "contract_version": "cv-H16"}, R1, idempotency_key="n")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and not git3.commits
