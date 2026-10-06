"""File-only baseline: equal invariant strength (matches the oracle on the same generated cases) and its own known-negatives."""
import random

import pytest

from baselines.h18_fileonly.ci import check
from baselines.h18_fileonly.repo import Model
from eoo_h18 import gen
from eoo_h18.base_run import run_case_baseline
from eoo_h18.rig import EooRig


@pytest.fixture(scope="module")
def rig(reader, tmp_path_factory):
    return EooRig(tmp_path_factory.mktemp("bl"), reader=reader)


def _run(rig, cases, evaluators=None):
    rows = []
    for c in cases:
        ref = rig.open_case(c, gen.case_hash(c))
        rows += run_case_baseline(c, rig.store.files_at(rig.last_start), evaluators or rig.evaluators)
    return rows


def test_baseline_matches_the_oracle_step_by_step_on_generated_cases(rig):
    rnd = random.Random(77)
    cases = [gen.gen_case(rnd, rig.base_ops, rig.commit0) for _ in range(250)]
    rows = _run(rig, cases)
    bad = [r for r in rows if r["accepted"] != r["oracle_legal"] or not r["summary_match"] or r["exception"]]
    assert len(rows) > 800 and bad == []


def test_baseline_ci_rejects_each_hostile_hand_edit(rig):
    files = rig.store.files_at(rig.root)
    m = Model(files)
    h = "H17"
    thr = sorted(k for k in m.keys("Threshold") if k.startswith("H17."))[0]
    from baselines.h18_fileonly.repo import set_object
    assert check(files, set_object(files, "Threshold", thr, {"value": 987}), rig.evaluators)  # H17 is PREREGISTERED
    assert check(files, set_object(files, "Hypothesis", h, {"phase": "EVALUATED"}), rig.evaluators)  # skips RUNNING and the verdict
    assert check(files, set_object(files, "Hypothesis", h, {"freeze_hash": ""}), rig.evaluators)
    assert check(files, {p: b for p, b in files.items() if "/Component/" not in p}, rig.evaluators)  # components are never deleted
    assert check(files, files, rig.evaluators) == []  # a no-op change is clean (known-negative of the checker)


def test_baseline_is_not_vacuous_removing_a_rule_makes_it_disagree(rig, monkeypatch):
    from baselines.h18_fileonly import ci
    monkeypatch.setattr(ci, "RULES", [])
    rnd = random.Random(77)
    cases = [gen.gen_case(rnd, rig.base_ops, rig.commit0) for _ in range(60)]
    rows = _run(rig, cases)
    assert any(r["accepted"] and not r["oracle_legal"] for r in rows)
