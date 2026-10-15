"""One unit test per project helper/read, on a hand-built world (prose of spec/ops/project.json)."""
import hashlib
import json

import pytest

from r3_oracle import helpers_project as H
from r3_oracle.view import HelperError
from tests.h23_util import view

E = lambda k: ("Experiment", k)  # noqa: E731
HY = lambda k: ("Hypothesis", k)  # noqa: E731


def world():
    objs = {
        "Hypothesis:H1": {"claim": "c1", "phase": "RUNNING", "freeze_hash": "ab"},
        "Hypothesis:H2": {"claim": "", "phase": "DRAFT"},
        "Hypothesis:H3": {"claim": "c3", "phase": "DRAFT"},
        "Rival:R1": {}, "Prediction:P1": {}, "Falsifier:F1": {},
        "Experiment:E1@v1": {"version": "1", "evidence_schema_ref": "s", "evaluator_ref": "neutral:evidence-present-v1"},
        "Experiment:E1@v2": {"version": "2", "evidence_schema_ref": "s", "evaluator_ref": "neutral:evidence-present-v1"},
        "Experiment:E9@v1": {"version": "1", "evidence_schema_ref": "", "evaluator_ref": "x"},
        "Experiment:E2@v1": {"version": "1a", "evidence_schema_ref": "s", "evaluator_ref": "unknown-eval"},
        "Metric:M1": {}, "Threshold:T1": {"value": {"min": 1}}, "Threshold:T0": {"value": 5},
        "Evidence:EV1": {"payload_hash": "h", "git_commit": "g", "experiment_version": "2", "environment": "e"},
        "Evidence:EV2": {"payload_hash": "h", "git_commit": "", "experiment_version": "2", "environment": "e"},
        "Evidence:EV3": {"payload_hash": "h", "git_commit": "g", "experiment_version": "1", "environment": "e"},
        "Commit:c1": {"committed_at": 10}, "Commit:c2": {"committed_at": 200},
        "Commit:c3": {"committed_at": 200},
        "ContractVersion:CV1": {}, "ContractVersion:CV1+2": {},
        "Component:K1": {}, "Component:K2": {}, "Component:K3": {},
        "Verdict:v-1": {},
    }
    links = [("HAS_RIVAL", "Hypothesis:H1", "Rival:R1"), ("PREDICTS", "Hypothesis:H1", "Prediction:P1"),
             ("FALSIFIED_BY", "Hypothesis:H1", "Falsifier:F1"),
             ("TESTED_BY", "Hypothesis:H1", "Experiment:E1@v1"), ("TESTED_BY", "Hypothesis:H1", "Experiment:E1@v2"),
             ("NEW_VERSION_OF", "Experiment:E1@v2", "Experiment:E1@v1"),
             ("TESTED_BY", "Hypothesis:H3", "Experiment:E9@v1"),
             ("MEASURES", "Experiment:E1@v1", "Metric:M1"), ("MEASURES", "Experiment:E1@v2", "Metric:M1"),
             ("GOVERNED_BY", "Metric:M1", "Threshold:T1"), ("GOVERNED_BY", "Metric:M1", "Threshold:T0"),
             ("PRODUCES", "Experiment:E1@v2", "Evidence:EV1"),
             ("SUPPORTS_OR_REFUTES", "Evidence:EV1", "Hypothesis:H1"),
             ("EXISTS_FOR", "Component:K1", "Hypothesis:H1"), ("EXISTS_FOR", "Component:K3", "Hypothesis:H3"),
             ("EVALUATES", "Verdict:v-1", "Hypothesis:H1")]
    objs["Hypothesis:H3"]["phase"] = "SUPERSEDED"
    return view(objs, links)


def test_hypothesis_id_for_claim():
    assert H.hypothesis_id_for_claim(world(), "claim") == "hyp-" + hashlib.sha256(b"claim").hexdigest()[:10]
    assert H.hypothesis_id_for_claim(world(), "ü") == "hyp-" + hashlib.sha256("ü".encode()).hexdigest()[:10]


def test_hypotheses_of_experiment_direct_and_via_predecessor_and_cycle_safe():
    v = world()
    assert H.hypotheses_of_experiment(v, E("E1@v1")) == [HY("H1")]
    assert H.hypotheses_of_experiment(v, E("E1@v2")) == [HY("H1")]
    v.links.add(("NEW_VERSION_OF", "Experiment:E1@v1", "Experiment:E1@v2"))
    v.links.discard(("TESTED_BY", "Hypothesis:H1", "Experiment:E1@v2"))
    v.links.discard(("TESTED_BY", "Hypothesis:H1", "Experiment:E1@v1"))
    assert H.hypotheses_of_experiment(v, E("E1@v2")) == []  # cycle, no hypothesis: terminates


def test_hypotheses_of_threshold_union():
    assert H.hypotheses_of_threshold(world(), ("Threshold", "T1")) == [HY("H1")]
    assert H.hypotheses_of_threshold(world(), ("Threshold", "NOPE")) == []


def test_contract_complete():
    v = world()
    assert H.contract_complete(v, HY("H1")) is True
    assert H.contract_complete(v, HY("H2")) is False  # blank claim
    assert H.contract_complete(v, HY("H3")) is False  # no rival/prediction/falsifier
    v.links.discard(("FALSIFIED_BY", "Hypothesis:H1", "Falsifier:F1"))
    assert H.contract_complete(v, HY("H1")) is False


def test_new_experiment_version_number_numeric_and_not():
    v = world()
    assert H.new_experiment_version_number(v, E("E1@v1")) == "2"
    assert H.new_experiment_version_number(v, E("E2@v1")) == "1a.1"


def test_new_experiment_id_and_contract_ids():
    v = world()
    assert H.new_experiment_id(v, E("E1@v1")) == "E1@v2"
    assert H.new_experiment_id(v, E("E2@v1")) == "E2@v1a.1"
    assert H.new_contract_version_id(v, E("E1@v1"), ("ContractVersion", "CV1")) == "CV1+2"
    assert H.existing_contract_version(v, E("E1@v1"), ("ContractVersion", "CV1")) == "CV1+2"
    assert H.existing_contract_version(v, E("E2@v1"), ("ContractVersion", "CV1")) is None


def test_head_commit_greatest_then_greatest_key_and_error():
    assert H.head_commit(world()) == "c3"
    with pytest.raises(HelperError):
        H.head_commit(view({}))


def test_evidence_experiment_and_pinned():
    v = world()
    assert H.evidence_experiment(v, HY("H1"), ("Evidence", "EV1")) == E("E1@v2")
    assert H.evidence_experiment(v, HY("H1"), ("Evidence", "EV3")) == E("E1@v1")
    assert H.evidence_experiment(v, HY("H1"), ("Evidence", "NOPE")) is None
    assert H.evidence_pinned(v, HY("H1"), ("Evidence", "EV1")) is True
    assert H.evidence_pinned(v, HY("H1"), ("Evidence", "EV2")) is False  # blank git_commit
    v.links.add(("TESTED_BY", "Hypothesis:H1", "Experiment:E2@v1"))
    v.objects["Experiment:E2@v1"]["version"] = "2"  # two experiments with version 2 -> ambiguous
    assert H.evidence_experiment(v, HY("H1"), ("Evidence", "EV1")) is None


def test_evidence_rebinding():
    v = world()
    assert H.evidence_rebinding(v, ("Evidence", "EV1")) is False
    assert H.evidence_rebinding(v, ("Evidence", "EV3")) is False  # nobody PRODUCES it
    v.links.add(("PRODUCES", "Experiment:E1@v1", "Evidence:EV1"))  # v1 produces a version-2 evidence
    assert H.evidence_rebinding(v, ("Evidence", "EV1")) is True


def test_evidence_count_and_next_verdict_id():
    v = world()
    assert H.evidence_count(v, HY("H1")) == 1 and H.evidence_count(v, HY("H2")) == 0
    assert H.next_verdict_id(v, HY("H1")) == "verdict-H1-2" and H.next_verdict_id(v, HY("H2")) == "verdict-H2-1"


def test_derive_verdict_precedence():
    v = world()
    assert H.derive_verdict(v, HY("H1")) == "SUPPORTED"
    v.objects["Hypothesis:H1"]["freeze_hash"] = ""
    assert H.derive_verdict(v, HY("H1")) == "INVALID"
    assert H.derive_verdict(v, HY("H2")) == "INCONCLUSIVE"  # no experiment: valid, incomplete
    v.links.discard(("SUPPORTS_OR_REFUTES", "Evidence:EV1", "Hypothesis:H1"))
    v.objects["Hypothesis:H1"]["freeze_hash"] = "ab"
    assert H.derive_verdict(v, HY("H1")) == "INCONCLUSIVE"  # evidence produced but not linked to the hypothesis
    v.links.add(("TESTED_BY", "Hypothesis:H2", "Experiment:E2@v1"))
    v.links.add(("PRODUCES", "Experiment:E2@v1", "Evidence:EV3"))
    v.objects["Evidence:EV3"]["experiment_version"] = "1a"
    with pytest.raises(HelperError):
        H.derive_verdict(v, HY("H2"))  # unknown evaluator fails closed


def test_verdict_reason_and_derivation_hash_are_stable_nonblank():
    v = world()
    assert "E1@v2" in H.verdict_reason(v, HY("H1")) and "evidence=1" in H.verdict_reason(v, HY("H1"))
    h = H.verdict_derivation_hash(v, HY("H1"))
    assert len(h) == 64 and h == H.verdict_derivation_hash(v, HY("H1"))
    v.objects["Evidence:EV1"]["payload_hash"] = "other"
    assert H.verdict_derivation_hash(v, HY("H1")) != h


def test_compute_freeze_hash_sorted_deduplicated_thresholds():
    v = world()
    body = {"evidence_schema_ref": "s", "evaluator_ref": "neutral:evidence-present-v1",
            "thresholds": [["T0", 5], ["T1", {"min": 1}]]}
    want = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert H.compute_freeze_hash(v, E("E1@v1")) == want


def test_find_orphan_components():
    assert H.find_orphan_components(world()) == ["K2", "K3"]  # K3 only exists for a SUPERSEDED hypothesis


def test_is_legal_transition():
    v = world()
    assert H.is_legal_transition(v, HY("H1"), "EVALUATED") is True
    assert H.is_legal_transition(v, HY("H1"), "SUPERSEDED") is False and H.is_legal_transition(v, HY("H1"), "DRAFT") is False
    assert H.is_legal_transition(v, HY("H3"), "DRAFT") is False  # SUPERSEDED is terminal


def test_canonical_state_hash_changes_with_state():
    v = world()
    h = H.canonical_state_hash(v)
    v.objects["Hypothesis:H1"]["phase"] = "EVALUATED"
    assert H.canonical_state_hash(v) != h and len(h) == 64


def test_head_commit_orders_numerically_not_as_strings():
    w = view({"Commit:a": {"committed_at": 50}, "Commit:b": {"committed_at": 100}})
    assert H.head_commit(w) == "b"
    with pytest.raises(HelperError):
        H.head_commit(view({"Commit:a": {"committed_at": "2026-01-01"}}))
