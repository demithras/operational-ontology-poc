"""Task classes TC2 (forensic queries) and TC3 (model change): both variants correct against the independent expectations."""
import pytest

from eoo_h18 import tc_eoo, tc_run
from eoo_h18.rig import EooRig


@pytest.fixture(scope="module")
def trig(reader, tmp_path_factory):
    return tc_run.tc_rig(reader, tmp_path_factory.mktemp("tc"))


def test_tc2_all_three_queries_correct_in_both_variants(trig, reader):
    r = tc_run.run_tc2(trig, reader)
    assert r["eoo_correct"] == {"q1": True, "q2": True, "q3": True} and r["baseline_correct"] == {"q1": True, "q2": True, "q3": True}
    assert r["expected"]["q2"] == ["cmp-legacy-draft"] and r["expected"]["q3"] == ["H18", "H19", "H20", "H21", "H22"]
    assert len(r["expected"]["q1"]["evidence"]) == 6 and r["expected"]["q1"]["verdict"] == "SUPPORTED"


def test_tc3_replication_rule_enforced_in_both_variants(trig, reader):
    r = tc_run.run_tc3(trig, reader)
    assert r["eoo_correct"] and r["baseline_correct"]
    assert [s["eoo_accept"] for s in r["steps"]] == [True, False, True, False] == [s["baseline_accept"] for s in r["steps"]]


def test_tc3_known_negative_without_the_lifecycle_rule_registration_is_wrong_in_eoo(reader, tmp_path):
    def extend(b):
        tc_eoo.extend(b)
        b.bind("precondition", "experiment is EVALUATED", lambda c: True)
    rig = EooRig(tmp_path, reader=reader, package=tc_eoo.patched_ir(), extend=extend, extra_ops=tc_eoo.dependency_ops(reader))
    assert tc_run.run_tc3(rig, reader)["eoo_correct"] is False


def test_tc3_known_negative_without_the_ci_rule_baseline_is_wrong(trig, reader, monkeypatch):
    from baselines.h18_fileonly import ci
    monkeypatch.setattr(ci, "RULES", [])
    assert tc_run.run_tc3(trig, reader)["baseline_correct"] is False


def test_tc2_known_negative_a_missing_dependency_link_changes_q3(reader, tmp_path):
    rig = EooRig(tmp_path, reader=reader, package=tc_eoo.patched_ir(), extend=tc_eoo.extend, extra_ops=[])  # no DEPENDS_ON links seeded
    assert tc_run.run_tc2(rig, reader)["eoo_correct"]["q3"] is False
