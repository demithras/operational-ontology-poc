"""Findings about the Project contract v2 that the H18 differential exposed, pinned (to v2, which stays byte-identical) so a change is
noticed (like P4b's FINDING tests). The v3 fix is proven in test_v3_h18.py."""
import json

from eoo_h18.rig import EooRig, PRINCIPAL
from domains._pack import load_ir


def _evaluated_case(rig, label):
    from eoo_h18.fixture import facts_for
    case = {"subject": "H16", "phase0": "RUNNING", "complete": {k: True for k in ("rival", "prediction", "falsifier", "evaluator")}, "evidence": [],
            "decision": None, "components": [], "facts": facts_for(rig.base_ops, "H16", rig.commit0), "ops": []}
    return case, rig.open_case(case, label)


def test_FINDING_self_supersession_is_accepted_because_the_conflict_policy_is_not_wired(rig_v2):
    ir = load_ir("project", "v2")
    sup = next(a for a in ir["actions"] if a["id"] == "supersede_hypothesis")
    assert "policy:conflicting_change_denied_with_conflict" not in sup["policy_refs"]  # declared in the IR, referenced by no action
    case, ref = _evaluated_case(rig_v2, "f1")
    for i, (a, inp) in enumerate([("evaluate_hypothesis", {"hypothesis": "H16"}), ("supersede_hypothesis", {"hypothesis": "H16", "successor": "H16"})]):
        rec = rig_v2.engine(ref).propose(a, inp, PRINCIPAL, idempotency_key=f"f1-{i}")
        assert rec["state"] == "RECONCILED_SUCCESS", (a, rec["state"])
    links = [p for p in rig_v2.store.files_at(rig_v2.store.head(ref)) if "SUPERSEDED_BY" in p and "H16__Hypothesis~H16" in p]
    assert links  # H16 -SUPERSEDED_BY-> H16 reached Git


def test_FINDING_new_experiment_version_is_not_linked_to_its_hypothesis_so_versions_cannot_chain(rig_v2):
    case, ref = _evaluated_case(rig_v2, "f2")
    e = rig_v2.engine(ref)
    rec = e.propose("new_experiment_version", {"experiment": "exp-h16-001", "contract_version": "cv-H16"}, PRINCIPAL, idempotency_key="f2-0")
    assert rec["state"] == "RECONCILED_SUCCESS"
    files = rig_v2.store.files_at(rig_v2.store.head(ref))
    assert any(p.endswith("exp-h16-001@v2.json") for p in files)
    assert not any("TESTED_BY" in p and "v2" in p for p in files)  # no TESTED_BY link: the new version is invisible to derive_verdict
    rec2 = rig_v2.engine(ref).propose("new_experiment_version", {"experiment": "exp-h16-001@v2", "contract_version": "cv-H16"}, PRINCIPAL, idempotency_key="f2-1")
    assert rec2["state"] == "DENIED" and rec2["gates"][-1]["gate"] == "preconditions"


def test_FINDING_freeze_hash_value_is_not_checked_against_the_frozen_files(rig_v2):
    case, ref = _evaluated_case(rig_v2, "f3")
    case["phase0"] = "DRAFT"
    ref = rig_v2.open_case(case, "f3b")
    rec = rig_v2.engine(ref).propose("preregister_hypothesis", {"hypothesis": "H16", "freeze_hash": "not-a-hash"}, PRINCIPAL, idempotency_key="f3-0")
    assert rec["state"] == "RECONCILED_SUCCESS"  # any non-blank string freezes the hypothesis
