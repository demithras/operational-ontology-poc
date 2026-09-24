"""Phase 10b item 6 (orchestrator correction): every hypothesis/acceptance/
exit-code derivation rule in scripts/gen_hypothesis_results.py and
scripts/gen_acceptance_verdict.py is tested here against a known-POSITIVE
fixture (a synthetic, all-green results directory) and a known-NEGATIVE
fixture (the SAME directory with one targeted signal flipped) — "a checker
that can't fail is not a checker."

This is exactly the discipline that would have caught bugs 3-4 of this
phase's own orchestrator review before they shipped: H14 checked for keys
that don't exist anywhere in this repo (always False, a permanent false
negative no green run could ever expose), and the hot-read-p95 acceptance
item read a "pass" field from the wrong nesting level (always None). A
positive-only test suite cannot catch either class of bug — a checker that
always returns the same value passes a positive-only test just as well as
a correct one. Every test here therefore asserts BOTH directions.

No docker/stack required — this suite works entirely against synthetic
JSON fixtures written to a temp directory, exercising the real derivation
functions directly (never re-implementing their logic).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import gen_acceptance_verdict, gen_fault_results, gen_hypothesis_results

# ---------------------------------------------------------------------------
# Golden (all-green) fixtures — one canonical dict per results file, built
# to match the REAL shapes read live from experiments/exp-001/results/*
# (verified by hand against that run before writing this suite).
# ---------------------------------------------------------------------------

ALL_F_IDS = [f"F{n:02d}" for n in range(1, 41)]

GATE_RELEVANT_F_IDS = [f"F{n:02d}" for n in range(1, 10)] + ["F22", "F23", "F24", "F26"] + [f"F{n:02d}" for n in range(30, 35)]
SAFETY_F_IDS = ["F01", "F02", "F03", "F04", "F05", "F06", "F16", "F17", "F30", "F31", "F32", "F33", "F34"]
DATA_QUALITY_F_IDS = ["F09", "F19", "F26", "F27", "F37", "F38", "F39"]
REPLAY_F_IDS = ["F28", "F29"]


def _golden_test_node(passed: bool = True) -> dict:
    return {"outcome": "passed" if passed else "failed", "message": None, "time_s": 0.01}


# Every substring _test_files_clean()/clean() ever matches on, each backed
# by one synthetic passing node id. Kept as one dict so both generator
# scripts' derivations see a fully populated `tests` map.
GOLDEN_TEST_SUBSTRINGS = [
    "tests/contracts/test_shacl_fixtures.py::test_x",
    "tests/contracts/test_shacl_rdf4j_transactional.py::test_x",
    "tests/agent/test_f04_undisclosed_tools.py::test_x",
    "tests/faults/test_divergence.py::test_x",
    "tests/faults/test_dependency_outage.py::test_x",
    "tests/faults/test_cdc_delay_and_kafka_outage.py::test_x",
    "tests/faults/test_wms_faults.py::test_x",
    "tests/faults/test_idempotency.py::test_x",
    "tests/faults/test_worker_crash.py::test_x",
    "tests/faults/test_commit_then_timeout.py::test_x",
    "tests/faults/test_kill_restart_convergence.py::test_x",
    "tests/stateful/test_live_differential.py::test_x",
    "tests/faults/test_concurrency_race.py::test_x",
    "tests/faults/test_concurrent_stock_receipt.py::test_x",
    "tests/model/test_stateful.py::test_x",
    "tests/model/test_bug_detection.py::test_x",
    "tests/contracts/test_compat_check.py::test_x",
    "tests/integration/test_canonical_scenario.py::test_x",
    "tests/replay/test_forensic_queries_v1_post_v3.py::test_x",
    "tests/integration/test_forensic_query_scaling.py::test_x",
    "tests/replay/test_f29_replay_integrity.py::test_x",
    "tests/integration/test_decision_service_delegation.py::test_x",
    "tests/replay/test_f29_tuple_snapshot_integrity.py::test_x",
]


def _golden_test_results() -> dict:
    tests = {node_id: _golden_test_node(True) for node_id in GOLDEN_TEST_SUBSTRINGS}
    return {"total": len(tests), "passed": len(tests), "failed": 0, "errors": 0, "skipped": 0, "elapsed_s": 1.0, "tests": tests}


def _golden_fault_results() -> dict:
    matrix = [
        {"id": fid, "description": f"synthetic {fid}", "status": "PASS",
         "test_ids": [f"tests/faults/test_{fid.lower()}.py::test_x"], "owning_phase": "test", "note": None}
        for fid in ALL_F_IDS
    ]
    aux = {"description": "synthetic", "status": "PASS", "test_ids": ["tests/faults/test_aux.py::test_x"], "note": None}
    return {
        "generated_at": "2026-01-01T00:00:00Z", "derived_from": "test-results.json",
        "summary": {"total": len(matrix), "PASS": len(matrix), "FAIL": 0, "NOT_TESTED": 0},
        "matrix": matrix, "kill_tests": dict(aux), "network_tests": dict(aux), "concurrency_test": dict(aux),
    }


def _golden_ab_results() -> dict:
    return {
        "W7_generated_incident_corpus": {"variants_decision_match_rate": 1.0},
        "W5_forensic_query": {"forensic": {"ontology": {"calls": 3}, "baseline": {"calls": 3}}},
        "W6_novel_cross_system_relation": {"effort": {"ontology": {"logical_lines": 40}, "baseline": {"logical_lines": 32}}},
        "hot_read_benchmark": {"ontology": 1.0, "baseline": 1.0},
        "ingestion_lag_benchmark": {"mean_lag_ms": {"ontology": 3000.0, "baseline": 700.0}, "max_lag_ms": {"ontology": 3500.0, "baseline": 1000.0}},
        "complexity_tax": {"total_containers_in_stack": 23, "ontology_extra_container_count": 6, "baseline_extra_container_count": 3},
    }


def _golden_mutation_results() -> dict:
    return {"mutations": [
        {"name": "IDEMPOTENCY_HANDLING", "target_killed": True},
        {"name": "RECONCILIATION_QUANTITY", "target_killed": True},
        {"name": "SHACL_CARDINALITY", "target_killed": True},
        {"name": "POLICY_COMPARATOR", "target_killed": True},
        {"name": "AUTHZ_RELATION", "target_killed": True},
    ]}


def _golden_evolution_comparison() -> dict:
    return {
        "replay_sweep": {
            "ontology_exit_code": 0,
            "baseline_summary": {"total_decisions": 220, "pass_like_count": 220, "pass_like_pct": 100.0, "fail_or_partial_count": 0},
        },
        "migration_effort": {
            "ontology_v1_to_v2": {"files_changed": 4, "insertions": 214, "deletions": 0, "commits": ["a"]},
            "ontology_v2_to_v3": {"files_changed": 6, "insertions": 249, "deletions": 0, "commits": ["b"]},
            "baseline_v1_to_v2_files_touched": [],
            "baseline_v2_to_v3_files_touched": [],
        },
    }


def _golden_latency() -> dict:
    q = {"count": 30, "p50_ms": 1.0, "p95_ms": 2.0, "p99_ms": 3.0, "max_ms": 4.0, "mean_ms": 1.5}
    return {
        "host_load": {"start": {"contended": False}, "end": {"contended": False}},
        "stage_benchmarks": {
            "bench_phase4": {"slo": {"measured_warm_p95_ms": 0.3, "name": "hot_read_p95_ms", "pass": True, "threshold_ms": 200}},
            "bench_phase5": {"slo": {
                "gate_evaluation_p95_ms": {"pass": True, "measured_worst_stage_p95_ms": 8.0, "threshold_ms": 300},
                "decision_proposal_p95_ms": {"pass": True, "measured_p95_ms": 30.0, "threshold_ms": 500},
            }},
            "bench_phase6": {},
        },
        "h13_forensic_query_latency": {"ontology": {"queries": {f"q{i}_x.rq": q for i in range(1, 10)}}, "baseline": {"queries": {}}},
    }


def _golden_structural_probe() -> dict:
    """Positive case: the baseline's own equivalent guard did NOT catch the
    corruption either way — the one scenario where H11 can be SUPPORTED."""
    return {"rejected_before_mutation": False, "replay_caught_it_after_mutation": False, "revert_clean": True,
            "finding": "synthetic: baseline caught nothing"}


def _golden_environment() -> dict:
    return {"git_commit": "deadbeef", "generated_at": "2026-01-01T00:00:00Z"}


def _write(results_dir: Path, name: str, obj: dict) -> None:
    (results_dir / name).write_text(json.dumps(obj, indent=2))


@pytest.fixture(autouse=True)
def _no_live_db(monkeypatch):
    """This whole suite must run without a live stack — _completeness_check()
    (H1) is the only derivation step that hits a real Postgres connection.
    Default to a clean "nothing missing" result so every OTHER test's
    derive() call doesn't pay a real (or failing) connection attempt;
    H1-specific tests override this explicitly to test both directions."""
    monkeypatch.setattr(gen_hypothesis_results, "_completeness_check", lambda: {"total": 10, "missing_count": 0, "required_fields": []})


@pytest.fixture
def golden(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    _write(d, "test-results.json", _golden_test_results())
    _write(d, "fault-results.json", _golden_fault_results())
    _write(d, "ab-results.json", _golden_ab_results())
    _write(d, "mutation-results.json", _golden_mutation_results())
    _write(d, "evolution-comparison.json", _golden_evolution_comparison())
    _write(d, "latency.json", _golden_latency())
    _write(d, "baseline-structural-mutation-probe.json", _golden_structural_probe())
    _write(d, "environment.json", _golden_environment())
    return d


def _mutate(golden_dir: Path, tmp_path: Path, name: str, patch) -> Path:
    """Copies the golden fixture set into a fresh dir, applies `patch` (a
    callable mutating the loaded dict for file `name`), rewrites it."""
    import shutil
    d2 = tmp_path / f"mut_{name}_{id(patch)}"
    shutil.copytree(golden_dir, d2)
    obj = json.loads((d2 / name).read_text())
    patch(obj)
    _write(d2, name, obj)
    return d2


# ---------------------------------------------------------------------------
# H1-H14: one positive + one targeted negative each.
# ---------------------------------------------------------------------------

def _hyp(results_dir: Path, hyp_id: str) -> str:
    doc = gen_hypothesis_results.derive(results_dir, "test-exp")
    return doc["hypotheses"][hyp_id]["status"]


def test_h1_positive(golden, monkeypatch):
    # _completeness_check() needs a live Postgres connection; mocked here so
    # H1's OWN derivation logic (not the DB round trip) is what's under test.
    monkeypatch.setattr(gen_hypothesis_results, "_completeness_check", lambda: {"total": 10, "missing_count": 0, "required_fields": []})
    assert _hyp(golden, "H1") == "SUPPORTED"


def test_h1_negative_f01_fails(golden, tmp_path, monkeypatch):
    monkeypatch.setattr(gen_hypothesis_results, "_completeness_check", lambda: {"total": 10, "missing_count": 0, "required_fields": []})
    def patch(d):
        d["matrix"][0]["status"] = "FAIL"  # F01
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    assert _hyp(d2, "H1") == "REJECTED"


def test_h1_negative_incomplete_decisions(golden, monkeypatch):
    monkeypatch.setattr(gen_hypothesis_results, "_completeness_check", lambda: {"total": 10, "missing_count": 3, "required_fields": []})
    assert _hyp(golden, "H1") == "REJECTED"


def test_h1_db_unreachable_is_inconclusive_not_rejected(golden, monkeypatch):
    monkeypatch.setattr(gen_hypothesis_results, "_completeness_check", lambda: {"total": 0, "missing_count": -1, "error": "connection refused"})
    assert _hyp(golden, "H1") == "INCONCLUSIVE"


def test_h2_positive(golden):
    assert _hyp(golden, "H2") == "SUPPORTED"


def test_h2_negative_gate_fault_fails(golden, tmp_path):
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F03":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    assert _hyp(d2, "H2") == "REJECTED"


def test_h2_ignores_f27_data_quality_fault(golden, tmp_path):
    """The specific bug the orchestrator found: F27 (data quality) must
    NOT move H2 (gate-relevant) — H2 stays SUPPORTED even if F27 fails."""
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F27":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    assert _hyp(d2, "H2") == "SUPPORTED"


def test_h3_positive(golden):
    assert _hyp(golden, "H3") == "SUPPORTED"


def test_h3_negative(golden, tmp_path):
    def patch(d):
        d["tests"]["tests/faults/test_divergence.py::test_x"]["outcome"] = "failed"
    d2 = _mutate(golden, tmp_path, "test-results.json", patch)
    assert _hyp(d2, "H3") == "REJECTED"


def test_h4_positive(golden):
    assert _hyp(golden, "H4") == "SUPPORTED"


def test_h4_negative_mutation_not_killed(golden, tmp_path):
    def patch(d):
        for m in d["mutations"]:
            if m["name"] == "IDEMPOTENCY_HANDLING":
                m["target_killed"] = False
    d2 = _mutate(golden, tmp_path, "mutation-results.json", patch)
    assert _hyp(d2, "H4") == "REJECTED"


def test_h5_positive(golden):
    assert _hyp(golden, "H5") == "SUPPORTED"


def test_h5_negative(golden, tmp_path):
    def patch(d):
        d["tests"]["tests/faults/test_concurrency_race.py::test_x"]["outcome"] = "failed"
    d2 = _mutate(golden, tmp_path, "test-results.json", patch)
    assert _hyp(d2, "H5") == "REJECTED"


def test_h6_positive(golden):
    assert _hyp(golden, "H6") == "SUPPORTED"


def test_h6_negative_slo_fails_uncontended(golden, tmp_path):
    def patch(d):
        d["stage_benchmarks"]["bench_phase5"]["slo"]["gate_evaluation_p95_ms"]["pass"] = False
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    assert _hyp(d2, "H6") == "REJECTED"


def test_h6_contended_is_inconclusive_not_rejected(golden, tmp_path):
    def patch(d):
        d["stage_benchmarks"]["bench_phase5"]["slo"]["gate_evaluation_p95_ms"]["pass"] = False
        d["host_load"]["start"]["contended"] = True
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    assert _hyp(d2, "H6") == "INCONCLUSIVE"


def test_h6_missing_hot_read_verdict_is_inconclusive_not_supported(golden, tmp_path):
    """Direct regression test for the orchestrator's second-pass finding:
    H6 used to read bench-phase4's missing/wrong-key "pass" as None, then
    `hot_read_pass is not False` waved it through as SUPPORTED. A real
    missing hot-read verdict must now produce INCONCLUSIVE, never
    SUPPORTED — no evidence is not evidence of success."""
    def patch(d):
        del d["stage_benchmarks"]["bench_phase4"]["slo"]["pass"]
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    assert _hyp(d2, "H6") == "INCONCLUSIVE"


def test_h6_real_hot_read_failure_is_rejected(golden, tmp_path):
    """The other half of the same regression: when hot_read genuinely DOES
    fail (a real measured False, not a missing key), H6 must be REJECTED,
    not silently passed through by the same bug in the other direction."""
    def patch(d):
        d["stage_benchmarks"]["bench_phase4"]["slo"]["pass"] = False
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    assert _hyp(d2, "H6") == "REJECTED"


def test_h6_cites_real_measured_numbers_in_notes(golden):
    """The orchestrator asked to confirm H6 cites a real hot-read p95
    number in the final report — verified here at the source: the notes
    string must embed the actual measured values, not just a bare pass
    boolean."""
    doc = gen_hypothesis_results.derive(golden, "test-exp")
    notes = doc["hypotheses"]["H6"]["notes"]
    assert "measured_warm_p95=0.3ms" in notes
    assert "gate_p95=8.0ms" in notes
    assert "proposal_p95=30.0ms" in notes


def test_h7_positive(golden):
    assert _hyp(golden, "H7") == "SUPPORTED"


def test_h7_negative(golden, tmp_path):
    def patch(d):
        d["replay_sweep"]["ontology_exit_code"] = 1
    d2 = _mutate(golden, tmp_path, "evolution-comparison.json", patch)
    assert _hyp(d2, "H7") == "REJECTED"


def test_h8_positive(golden):
    assert _hyp(golden, "H8") == "SUPPORTED"


def test_h8_negative_compat_check_fails(golden, tmp_path):
    def patch(d):
        d["tests"]["tests/contracts/test_compat_check.py::test_x"]["outcome"] = "failed"
    d2 = _mutate(golden, tmp_path, "test-results.json", patch)
    assert _hyp(d2, "H8") == "REJECTED"


def test_h9_positive(golden):
    assert _hyp(golden, "H9") == "SUPPORTED"


def test_h9_negative(golden, tmp_path):
    def patch(d):
        d["tests"]["tests/agent/test_f04_undisclosed_tools.py::test_x"]["outcome"] = "failed"
    d2 = _mutate(golden, tmp_path, "test-results.json", patch)
    assert _hyp(d2, "H9") == "REJECTED"


def test_h10_positive(golden):
    assert _hyp(golden, "H10") == "SUPPORTED"


def test_h10_negative(golden, tmp_path):
    def patch(d):
        d["tests"]["tests/integration/test_canonical_scenario.py::test_x"]["outcome"] = "failed"
    d2 = _mutate(golden, tmp_path, "test-results.json", patch)
    assert _hyp(d2, "H10") == "REJECTED"


def test_h11_positive_supported_when_baseline_does_not_catch_it(golden):
    assert _hyp(golden, "H11") == "SUPPORTED"


def test_h11_negative_rejected_when_baseline_catches_it_too(golden, tmp_path):
    """This IS the orchestrator's own correction, encoded as a regression
    test: if the baseline's equivalent guard also catches the corruption
    (like-for-like), H11 must NOT claim an ontology-specific advantage."""
    def patch(d):
        d["rejected_before_mutation"] = True
    d2 = _mutate(golden, tmp_path, "baseline-structural-mutation-probe.json", patch)
    assert _hyp(d2, "H11") == "REJECTED"


def test_h12_positive(golden):
    assert _hyp(golden, "H12") == "SUPPORTED"


def test_h12_negative_f16_fails(golden, tmp_path):
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F16":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    assert _hyp(d2, "H12") == "REJECTED"


def test_h13_positive(golden):
    assert _hyp(golden, "H13") == "SUPPORTED"


def test_h13_negative_no_samples(golden, tmp_path):
    def patch(d):
        for q in d["ontology"]["queries"].values():
            q["count"] = 0
    d2 = _mutate(golden, tmp_path, "latency.json", lambda full: patch(full["h13_forensic_query_latency"]))
    assert _hyp(d2, "H13") == "REJECTED"


def test_h14_positive(golden):
    """Regression test for the orchestrator's bug 3: this must read the
    REAL contracts/actions/*/*.yaml files (evidence_requirements +
    closure.required), which are always present in this repo, so H14 is
    SUPPORTED as long as F02 passes — it must NOT be a permanent False."""
    assert _hyp(golden, "H14") == "SUPPORTED"


def test_h14_negative_f02_fails(golden, tmp_path):
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F02":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    assert _hyp(d2, "H14") == "REJECTED"


def test_h14_checker_reads_the_real_yaml_keys(tmp_path, monkeypatch):
    """Direct unit test of the checker itself (not the whole derive()
    pipeline) against synthetic action YAML — proves it reads
    `evidence_requirements`/`closure.required` (the real keys) and would
    correctly return False for a file missing them, not just True always."""
    actions_dir = tmp_path / "contracts" / "actions" / "v1"
    actions_dir.mkdir(parents=True)
    good = actions_dir / "good_action.yaml"
    good.write_text(yaml.safe_dump({"evidence_requirements": ["x"], "closure": {"required": ["y"]}}))
    bad = actions_dir / "bad_action.yaml"
    bad.write_text(yaml.safe_dump({"required_evidence": ["x"], "evidence": {"required": ["y"]}}))  # the OLD, wrong keys

    monkeypatch.setattr(gen_hypothesis_results, "REPO_ROOT", tmp_path)
    result = gen_hypothesis_results._actions_declare_required_evidence()
    assert result[str(Path("contracts/actions/v1/good_action.yaml"))] is True
    assert result[str(Path("contracts/actions/v1/bad_action.yaml"))] is False


# ---------------------------------------------------------------------------
# gen_acceptance_verdict.py: the specific bugs found, plus exit-code mapping
# ---------------------------------------------------------------------------

def _verdict_and_hyps(results_dir: Path) -> tuple[dict, dict]:
    hyp_doc = gen_hypothesis_results.derive(results_dir, "test-exp")
    verdict = gen_acceptance_verdict.derive(results_dir)
    return verdict, hyp_doc["hypotheses"]


def test_hot_read_p95_positive_and_negative(golden, tmp_path):
    """Regression test for the orchestrator's bug 4: the old code always
    read None here regardless of the real value."""
    v, _ = _verdict_and_hyps(golden)
    assert v["can_decide_now_items"]["2_hot_read_p95"] is True

    def patch(d):
        d["stage_benchmarks"]["bench_phase4"]["slo"]["pass"] = False
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    v2, _ = _verdict_and_hyps(d2)
    assert v2["can_decide_now_items"]["2_hot_read_p95"] is False


def test_exit_code_0_when_everything_clean(golden):
    v, _ = _verdict_and_hyps(golden)
    assert v["exit_code"] == 0
    assert v["safety_fail"] is False


def test_exit_code_10_on_safety_relevant_fault(golden, tmp_path):
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F03":  # unauthorized human -> deny; 0 external effects
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    v, _ = _verdict_and_hyps(d2)
    assert v["exit_code"] == 10
    assert v["safety_fail"] is True


def test_exit_code_never_10_on_data_quality_fault_f27(golden, tmp_path):
    """Regression test for the orchestrator's bug 2: F27 (data quality,
    spec 11 'Data-quality acceptance') must never produce exit code 10
    (safety)."""
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F27":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    v, _ = _verdict_and_hyps(d2)
    assert v["exit_code"] != 10
    assert v["safety_fail"] is False
    assert v["data_quality_fail"] is True
    assert v["exit_code"] == 11


def test_exit_code_12_on_replay_fault(golden, tmp_path):
    def patch(d):
        for m in d["matrix"]:
            if m["id"] == "F28":
                m["status"] = "FAIL"
        d["summary"]["FAIL"] = 1
        d["summary"]["PASS"] -= 1
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    v, _ = _verdict_and_hyps(d2)
    assert v["exit_code"] == 12
    assert v["safety_fail"] is False


def test_exit_code_13_on_uncontended_perf_slo_miss(golden, tmp_path):
    def patch(d):
        d["stage_benchmarks"]["bench_phase4"]["slo"]["pass"] = False
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    v, _ = _verdict_and_hyps(d2)
    assert v["exit_code"] == 13


def test_exit_code_15_when_test_results_missing(golden):
    (golden / "test-results.json").unlink()
    v, _ = _verdict_and_hyps(golden)
    assert v["exit_code"] == 15


# ---------------------------------------------------------------------------
# gen_fault_results.py: status derivation from live test outcomes
# ---------------------------------------------------------------------------

def test_fault_results_pass_when_mapped_tests_pass():
    catalog_matrix = [{"id": "F01", "description": "x", "test_node_ids": ["tests/x.py::test_a"], "owning_phase": "p", "note": None}]
    outcomes = {"tests/x.py::test_a": {"outcome": "passed", "message": None}}
    status, note = gen_fault_results._status_for(catalog_matrix[0]["test_node_ids"], outcomes)
    assert status == "PASS"


def test_fault_results_fail_when_mapped_test_fails():
    outcomes = {"tests/x.py::test_a": {"outcome": "failed", "message": "boom"}}
    status, note = gen_fault_results._status_for(["tests/x.py::test_a"], outcomes)
    assert status == "FAIL"
    assert "failed" in note


def test_fault_results_not_tested_when_nothing_collected():
    status, note = gen_fault_results._status_for(["tests/x.py::test_a"], {})
    assert status == "NOT_TESTED"
    assert note is not None


# ---------------------------------------------------------------------------
# _status() / _hyp_bool(): the None-propagation contract itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inputs,expected", [
    ((True, True), "SUPPORTED"),
    ((True, False), "REJECTED"),
    ((True, None), "INCONCLUSIVE"),
    ((None, None), "INCONCLUSIVE"),
    ((False,), "REJECTED"),
])
def test_status_helper_contract(inputs, expected):
    assert gen_hypothesis_results._status(*inputs) == expected


@pytest.mark.parametrize("status,expected", [
    ("SUPPORTED", True), ("REJECTED", False), ("INCONCLUSIVE", None), ("MISSING_KEY", None),
])
def test_hyp_bool_never_reads_inconclusive_as_false(status, expected):
    hyps = {"H1": {"status": status}} if status != "MISSING_KEY" else {}
    assert gen_acceptance_verdict._hyp_bool(hyps, "H1") is expected


# ---------------------------------------------------------------------------
# Broader sweep (orchestrator-requested, Phase 10b second pass): every OTHER
# "id not found" / "block missing" path that could silently read as ok/not-ok
# instead of None/INCONCLUSIVE.
# ---------------------------------------------------------------------------

def test_all_pass_empty_and_missing_id_are_none_not_false():
    assert gen_hypothesis_results._all_pass({}) is None
    assert gen_hypothesis_results._all_pass({"F01": "PASS", "F02": "MISSING"}) is None
    assert gen_hypothesis_results._all_pass({"F01": "PASS", "F02": "PASS"}) is True
    assert gen_hypothesis_results._all_pass({"F01": "PASS", "F02": "FAIL"}) is False


def test_h13_empty_queries_is_inconclusive_not_rejected(golden, tmp_path):
    def patch(full):
        full["h13_forensic_query_latency"]["ontology"]["queries"] = {}
    d2 = _mutate(golden, tmp_path, "latency.json", patch)
    assert _hyp(d2, "H13") == "INCONCLUSIVE"


def test_h7_missing_replay_sweep_is_inconclusive_not_rejected(golden, tmp_path):
    def patch(d):
        del d["replay_sweep"]
    d2 = _mutate(golden, tmp_path, "evolution-comparison.json", patch)
    assert _hyp(d2, "H7") == "INCONCLUSIVE"


def test_h8_missing_replay_sweep_is_inconclusive_not_rejected(golden, tmp_path):
    def patch(d):
        del d["replay_sweep"]
    d2 = _mutate(golden, tmp_path, "evolution-comparison.json", patch)
    assert _hyp(d2, "H8") == "INCONCLUSIVE"


def test_fault_pass_missing_id_is_none_not_false():
    fault_doc = {"matrix": [{"id": "F01", "status": "PASS"}]}
    assert gen_acceptance_verdict._fault_pass(fault_doc, "F01") is True
    assert gen_acceptance_verdict._fault_pass(fault_doc, "F99_DOES_NOT_EXIST") is None
    assert gen_acceptance_verdict._fault_pass(None, "F01") is None


def test_acceptance_item_5_missing_fault_id_is_inconclusive(golden, tmp_path):
    """F03 present-but-missing-from-the-matrix (not merely FAIL) must read
    as INCONCLUSIVE for item 5, never a silently fabricated FAIL."""
    def patch(d):
        d["matrix"] = [m for m in d["matrix"] if m["id"] != "F03"]
    d2 = _mutate(golden, tmp_path, "fault-results.json", patch)
    v, _ = _verdict_and_hyps(d2)
    assert v["can_decide_now_items"]["5_unauthorized_zero_effects"] is None
