"""Mutation proof: perturbing cost accounting to ignore one variant's equivalent glue is detected by the fairness check and the evaluator."""
import copy
import json

import pytest
from conftest import make_case, rewrite

from eoo_h22 import facts, fairness
from eoo_h22.evaluate import evaluate

SNAP = facts.h18_snapshot()
OWNER = {  # the check that must catch each mutant
    "M1_eoo_python_glue_zeroed_in_totals": "eoo: python_loc stated 0",
    "M2_baseline_python_assignment_dropped": "baseline: python_loc stated",
    "M3_baseline_python_glue_dropped_consistently": "baseline: no python glue counted",
    "M4_eoo_recurring_tax_ignored": "eoo: recurring complexity not counted",
}


def test_control_is_clean():
    assert fairness.asymmetries(SNAP) == []
    assert fairness.asymmetries(copy.deepcopy(SNAP)) == []


def test_snapshot_matches_the_committed_h18_numbers():
    pc = SNAP["per_class"]
    assert {c: pc[c]["ratio_eoo_over_baseline"] for c in pc} == {"TC1": 5.259, "TC2": 3.714, "TC3": 3.971}
    assert SNAP["recurring_complexity_loc"] == {"baseline": 39, "eoo": 2191}


@pytest.mark.parametrize("mid", sorted(OWNER))
def test_each_ignore_glue_mutant_is_detected_by_its_check(mid):
    out = fairness.asymmetries(fairness.ignore_glue_mutants(SNAP)[mid])
    assert out and any(OWNER[mid] in x for x in out), out


def test_all_four_mutants_exist_and_only_the_control_is_clean():
    m = fairness.ignore_glue_mutants(SNAP)
    assert sorted(m) == sorted(OWNER) and all(fairness.asymmetries(x) for x in m.values())


def test_a_symmetric_change_is_not_flagged():
    s = copy.deepcopy(SNAP)
    # baseline TC2 gains a config file, recorded consistently in the assignment, the per-class row, the total and the ratio: still fair
    s["assignment"]["baseline"]["config"]["TC2"] = {"x.json": 5}
    s["assignment"]["eoo"]["config"]["TC2"] = {k: v for k, v in s["assignment"]["eoo"]["config"]["TC2"].items()}
    s["per_class"]["TC2"]["baseline"].update(config_lines=5, total=26, total_without_extras=26)
    s["per_class"]["TC2"]["ratio_eoo_over_baseline"] = round(78 / 26, 3)
    assert fairness.asymmetries(s) == []


def test_task_level_asymmetry_known_negatives():
    ok = {"task_id": "a", "eoo_components": {"c": 1, "g": 2}, "baseline_components": {"c": 3, "g": 4}}
    assert fairness.task_asymmetries([ok]) == []
    assert fairness.task_asymmetries([{**ok, "baseline_components": {"c": 3}}])
    assert fairness.task_asymmetries([{**ok, "eoo_components": {"c": 1, "g": None}}])
    assert fairness.task_asymmetries([{"task_id": "z"}])


@pytest.mark.parametrize("mid", sorted(OWNER))
def test_evaluator_turns_a_glue_ignoring_accounting_into_invalid(real_run, tmp_path, mid):
    import shutil
    d = tmp_path / "ev"
    shutil.copytree(real_run, d)
    clean = evaluate(d)
    assert clean["verdict"] == "INCONCLUSIVE" and not clean["numbers"]["accounting_asymmetries"]
    rewrite(d, "runtime-tax.json", lambda p: p["fairness_context"].update(h18_snapshot=fairness.ignore_glue_mutants(SNAP)[mid]))
    v = evaluate(d)
    assert v["verdict"] == "INVALID" and v["numbers"]["accounting_asymmetries"]
    assert [r["value"] for r in v["predicates"]["invalid_if"] if r["id"] == "V2"] == [True]


def test_fairness_check_sees_the_h18_bespoke_metrics_file_itself():
    p = json.loads((facts.ROOT / facts.H18_METRICS).read_text())["payload"]
    assert fairness.asymmetries({k: p[k] for k in SNAP}) == []
