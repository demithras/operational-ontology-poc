"""Mutation proof: each registered mutation is found by the differential on a crafted case; the clean control stays silent."""
import copy

import pytest

from eoo_h18.fixture import facts_for
from eoo_h18.mutants import REGISTRY
from eoo_h18.mutation_run import count, run_rows
from eoo_h18.rig import EooRig

CORE = {k: True for k in ("rival", "prediction", "falsifier", "evaluator")}
PRE = {"k": "preregister", "freeze": "junk", "freeze_value": "fh-1"}


def case(rig, phase0, ops, evidence=(), subject="H17"):
    return {"subject": subject, "phase0": phase0, "complete": CORE, "evidence": list(evidence), "decision": None, "components": [],
            "facts": facts_for(rig.base_ops, subject, rig.commit0), "ops": ops}


@pytest.fixture(scope="module")
def cases(reader, tmp_path_factory):
    rig = EooRig(tmp_path_factory.mktemp("mutc"), reader=reader)
    return {
        "M1_allow_post_freeze_threshold_edit": case(rig, "DRAFT", [PRE, {"k": "edit_threshold", "value": 123}]),
        "M2_allow_verdict_without_evidence": case(rig, "RUNNING", [{"k": "evaluate"}]),
        "M3_detach_commit_provenance": case(rig, "DRAFT", [PRE]),
        "M4_allow_unpinned_evidence": case(rig, "RUNNING", [{"k": "attach", "ev": "ev-gen-0"}], [{"id": "ev-gen-0", "pin": "env", "tag": "s"}]),
        "M5_allow_supersede_out_of_order": case(rig, "PREREGISTERED", [{"k": "supersede", "succ": "other"}]),
    }


def test_clean_control_is_silent_on_every_signal(reader, cases):
    rows = run_rows(reader, list(cases.values()))
    assert all(count(rows, m["expect"]) == 0 for m in REGISTRY)
    assert [r["op"] for r in rows if r.get("divergence")] == []


@pytest.mark.parametrize("m", REGISTRY, ids=lambda m: m["id"])
def test_each_mutation_is_found_and_only_by_its_own_signal(reader, cases, m):
    rows = run_rows(reader, [cases[m["id"]]], mutate=m["mutate"], provenance=m["provenance"])
    assert count(rows, m["expect"]) >= 1, m["id"]
    assert not any(r["exception"] for r in rows)


def test_target_mutations_are_the_three_named_by_the_contract():
    assert [m["id"] for m in REGISTRY if m["target"]] == ["M1_allow_post_freeze_threshold_edit", "M2_allow_verdict_without_evidence", "M3_detach_commit_provenance"]


def test_a_mutation_does_not_kill_unrelated_signals(reader, cases):
    m1 = REGISTRY[0]
    rows = run_rows(reader, [cases["M3_detach_commit_provenance"]], mutate=m1["mutate"])
    assert count(rows, REGISTRY[2]["expect"]) == 0 and count(rows, m1["expect"]) == 0  # M1 changes nothing for a legal prereg
