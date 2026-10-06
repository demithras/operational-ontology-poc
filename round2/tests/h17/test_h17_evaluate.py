"""Evaluator: known-positive -> SUPPORTED; for EACH reject / inconclusive / invalid clause a known-negative flips it."""
import json
from pathlib import Path

import pytest

from eoo_h17.evaluate import evaluate

CLAUSES = ("S1", "S2", "S3", "S4", "R1", "R2", "R3", "I1", "I2", "I3", "V1", "V2", "V3", "V4")


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def flipped(base, v):
    b, x = vals(base), vals(v)
    return sorted(k for k in b if b[k] != x[k])


@pytest.fixture(scope="module")
def base(positive_dir):
    return evaluate(positive_dir)


def test_known_positive_is_supported(base):
    assert base["verdict"] == "SUPPORTED", (base["verdict"], base["problems"], vals(base))
    assert [k for k, x in vals(base).items() if k[0] == "S" and x is not True] == []
    assert [k for k, x in vals(base).items() if k[0] in "RIV" and x is not False] == []


def test_function_only_trace_with_effect_is_rejected(base, edit):
    def f(p):
        r = p["function_only_traces"][0]
        r.update(effect_log_after=1, effect_digest_equal=False, identical=False)
    v = evaluate(edit("effect-log-audit.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R1", "S1"], flipped(base, v)


def test_function_only_external_effect_alone_is_rejected(base, edit):
    def f(p):
        p["function_only_traces"][0].update(external_after=1, external_equal=False)
    v = evaluate(edit("effect-log-audit.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R1", "S1"]


def test_negative_action_with_effect_is_rejected(base, edit):
    def f(p):
        p["negative_cases"][0].update(effect_log_delta=1, zero_effects=False)
    v = evaluate(edit("negative-action-results.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R2", "S2"]


def test_agent_tamper_violation_is_rejected(base, edit):
    def f(p):
        next(a for a in p["agent_attacks"] if a["attack"] == "tamper_returned_record").update(violation=True, world_changed=True)
    v = evaluate(edit("negative-action-results.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R2", "S2"]


def test_tamper_control_with_effect_is_a_harness_problem_not_a_reject(base, edit):
    def f(p):
        next(a for a in p["agent_attacks"] if a["attack"] == "control_no_tamper").update(violation=True)
    v = evaluate(edit("negative-action-results.json", f))
    assert flipped(base, v) == ["I3", "S2"] and v["verdict"] == "INCONCLUSIVE"


def test_agent_raw_write_is_rejected(base, edit):
    def f(p):
        next(a for a in p["agent_attacks"] if a["category"] == "raw_write").update(violation=True)
    v = evaluate(edit("negative-action-results.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R3", "S2"]


def test_disclosed_limit_row_is_not_counted(base, edit):
    def f(p):
        next(a for a in p["agent_attacks"] if a["category"] == "disclosed_limit").update(violation=True)
    v = evaluate(edit("negative-action-results.json", f))
    assert v["verdict"] == "SUPPORTED" and flipped(base, v) == []


def test_gate_failure_in_state_machine_is_rejected(base, edit):
    def f(p):
        p["per_domain"]["project"]["failures"].append({"kind": "gate_mismatch", "detail": "x", "steps": [["init", "std"]]})
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R2", "S2", "S4"]


def test_function_effect_in_state_machine_is_rejected(base, edit):
    def f(p):
        p["per_domain"]["project"]["failures"].append({"kind": "function_effect", "detail": "x", "steps": [["init", "std"]]})
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R1", "S1", "S4"]


def test_missing_domain_or_class_is_inconclusive(base, edit):
    def f(p):
        for r in p["cases"]:
            if r["domain"] == "project":
                r["classes"] = [c for c in r["classes"] if c != "crash_restart"]
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I1"]


def test_missing_domain_is_inconclusive(base, edit):
    v = evaluate(edit("state-machine-results.json", lambda p: p.update(cases=[r for r in p["cases"] if r["domain"] == "manufacturing"])))
    assert v["verdict"] == "INCONCLUSIVE" and vals(v)["I1"] is True and vals(v)["S4"] is False


def test_too_few_traces_is_inconclusive(base, edit):
    def f(p):
        del p["cases"][4000:]
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I2", "S4"]


def test_oracle_disagreement_is_inconclusive(base, edit):
    def f(p):
        p["per_domain"]["manufacturing"]["failures"].append({"kind": "execution_class", "detail": "x", "steps": [["init", "std"]]})
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I3", "S4"]


def test_too_few_function_only_traces_is_inconclusive(base, edit):
    def f(p):
        p["function_only_traces"] = [r for r in p["function_only_traces"] if r["domain"] == "manufacturing" or int(r["sha"].split("-")[-1]) < 500]
    v = evaluate(edit("effect-log-audit.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I3"]


def test_unexpected_attack_exception_is_inconclusive(base, edit):
    def f(p):
        p["agent_attacks"][0].update(unexpected_exception=True)
    v = evaluate(edit("negative-action-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I3"]


def test_surviving_mutant_blocks_support(base, edit):
    def f(p):
        p["mutants"][0].update(killed=False, killed_by_expected_signal=False)
    v = evaluate(edit("mutation-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S3"]


def test_mutant_killed_by_wrong_signal_is_a_survivor(base, edit):
    def f(p):
        p["mutants"][0]["killed_by_expected_signal"] = False
    assert flipped(base, evaluate(edit("mutation-results.json", f))) == ["S3"]


def test_missing_counterexample_blocks_support(base, edit):
    def f(p):
        p["mutants"][0]["counterexample"]["steps"] = []
    assert flipped(base, evaluate(edit("mutation-results.json", f))) == ["S3"]


def test_oracle_importing_the_engine_is_invalid(base, edit):
    def f(p):
        p["oracle"]["imports"].append("eoo_engine")
        p["oracle"]["forbidden_imports"].append("eoo_engine")
    v = evaluate(edit("state-machine-results.json", f))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V3"]


def test_oracle_file_changed_after_the_run_is_invalid(base, edit):
    v = evaluate(edit("state-machine-results.json", lambda p: p["oracle"].update(sha256="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V3"]


def test_dirty_mutation_control_is_invalid(base, edit):
    v = evaluate(edit("mutation-results.json", lambda p: p["controls"].update(clean=False)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["S3", "V4"]


def test_engine_files_dirty_is_invalid(base, edit):
    v = evaluate(edit("state-machine-results.json", lambda p: p["engine_files"].update(clean=False, paths_dirty=["round2/src/eoo_engine/x.py"])))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V4"]


def test_wrong_protocol_hash_is_invalid(base, edit):
    v = evaluate(edit("effect-log-audit.json", record_fn=lambda r: r.update(protocol_freeze_hash="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_wrong_prereg_hash_is_invalid(base, edit):
    v = evaluate(edit("effect-log-audit.json", record_fn=lambda r: r.update(engine_prereg_sha256="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_disagreeing_provenance_is_invalid(base, edit):
    v = evaluate(edit("effect-log-audit.json", record_fn=lambda r: r.update(seed=999)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


@pytest.mark.parametrize("name", ["state-machine-results.json", "effect-log-audit.json", "negative-action-results.json",
                                  "mutation-results.json"])
def test_missing_evidence_never_supports(edit, name):
    v = evaluate(edit(drop=name))
    assert v["verdict"] in ("INCONCLUSIVE", "INVALID") and v["common"]["required_evidence_complete"] is False
    assert any(name in p and "missing" in p for p in v["problems"])


def test_tampered_payload_never_supports(edit):
    d = edit()
    rec = json.loads((d / "effect-log-audit.json").read_text())
    rec["payload"]["function_only_traces"][0]["effect_log_after"] = 7  # hash not refreshed
    (d / "effect-log-audit.json").write_text(json.dumps(rec))
    v = evaluate(d)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_every_contract_clause_has_a_predicate(base):
    assert sorted(vals(base)) == sorted(CLAUSES)
    c = json.loads((Path(__file__).resolve().parents[2] / "hypotheses/h17/contract.json").read_text())["evaluator"]
    for k in ("support_if", "reject_if", "inconclusive_if", "invalid_if"):
        assert len(base["predicates"][k]) >= len(c[k])
