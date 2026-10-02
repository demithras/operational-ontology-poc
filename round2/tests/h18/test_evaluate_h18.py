"""Evaluator: a known-positive is SUPPORTED; for EACH reject / inconclusive / invalid clause a known-negative flips exactly it."""
import pytest

from eoo_h18.evaluate import evaluate


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def flipped(base, v):
    b, x = vals(base), vals(v)
    return sorted(k for k in b if b[k] != x[k])


@pytest.fixture(scope="module")
def base(positive_dir):
    return evaluate(positive_dir)


def test_known_positive_is_supported(base):
    assert base["verdict"] == "SUPPORTED", (base["verdict"], base["problems"], vals(base), base["protocol_mismatches"])
    assert [k for k, x in vals(base).items() if k[0] == "S" and x is not True] == [] and [k for k, x in vals(base).items() if k[0] in "RIV" and x is not False] == []
    assert base["numbers"]["unique_cases"] == 3000 and base["engine_version"] == "1.1"


def test_illegal_accepted_in_a_core_class_is_rejected(base, edit):
    def f(p):
        s = p["cases"][0]["steps"][0]
        s["cls"], s["legal"] = ["post_freeze_threshold_edit"], False
        s["eoo"].update(acc=True, div="illegal_accepted")
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "REJECTED" and {"R1", "S1"} <= set(flipped(base, v)) and vals(v)["R1"] is True, flipped(base, v)


def test_illegal_accepted_in_an_extension_class_blocks_support_without_rejecting(base, edit):
    def f(p):
        s = p["cases"][0]["steps"][0]
        s["cls"], s["legal"] = ["supersede_self"], False
        s["eoo"].update(acc=True, div="illegal_accepted")
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and "S1" in flipped(base, v) and vals(v)["R1"] is False


def test_parity_or_worse_surface_in_every_class_is_rejected(base, edit):
    def f(p):
        for c in p["per_class"].values():
            c["eoo"]["total"] = 150
        p["recurring_complexity_loc"] = {"eoo": 500, "baseline": 20, "eoo_files": []}
    v = evaluate(edit("bespoke-change-metrics.json", f))
    assert v["verdict"] == "REJECTED" and vals(v)["R2"] is True and vals(v)["S5"] is False


def test_less_than_25_percent_reduction_is_not_support(base, edit):
    def f(p):
        for c in p["per_class"].values():
            c["eoo"]["total"] = 90
    v = evaluate(edit("bespoke-change-metrics.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S5"]


def test_reduction_with_correctness_loss_is_not_support(base, edit):
    def f(p):
        for c in p["per_class"].values():
            c["correctness"] = {"eoo": False, "baseline": True}
    v = evaluate(edit("bespoke-change-metrics.json", f))
    assert vals(v)["S5"] is False and v["verdict"] != "SUPPORTED"


def test_domain_branch_in_the_engine_is_rejected(base, edit):
    def f(p):
        p["engine_domain_audit"]["project_domain_branches"] = 1
        p["engine_domain_audit"]["domain_identity_branches"] = 1
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "REJECTED" and vals(v)["R3"] is True and vals(v)["S4"] is False


def test_baseline_disagreeing_with_the_oracle_is_inconclusive(base, edit):
    def f(p):
        s = p["cases"][0]["steps"][0]
        s["base"].update(acc=False, div="legal_rejected")
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I1"]


def test_baseline_tc_incorrect_is_inconclusive(base, edit):
    v = evaluate(edit("baseline-comparison.json", lambda p: p["tc3"].update(baseline_correct=False)))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I1"]


def test_too_few_unique_cases_is_inconclusive(base, edit):
    v = evaluate(edit("project-state-machine.json", lambda p: p.update(cases=p["cases"][:100])))
    assert v["verdict"] == "INCONCLUSIVE" and {"I2", "S1"} <= set(flipped(base, v))


def test_a_class_never_generated_is_inconclusive(base, edit):
    def f(p):
        for c in p["cases"]:
            c["steps"] = [s for s in c["steps"] if "flag_non_orphan" not in s["cls"]]
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I2"]


def test_surviving_target_mutant_blocks_support(base, edit):
    v = evaluate(edit("mutation-results.json", lambda p: p["mutants"][0].update(killed=False)))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S6"]


def test_dirty_mutation_control_is_invalid(base, edit):
    v = evaluate(edit("mutation-results.json", lambda p: p["controls"].update(clean=False)))
    assert v["verdict"] == "INVALID" and vals(v)["V3"] is True


def test_harness_error_rows_are_invalid(base, edit):
    def f(p):
        p["cases"][0]["steps"][0]["eoo"]["exc"] = "KeyError: x"
    v = evaluate(edit("project-state-machine.json", f))
    assert v["verdict"] == "INVALID" and vals(v)["V3"] is True


def test_changed_harness_file_since_the_run_is_invalid(base, edit):
    def r(rec):
        k = sorted(rec["harness_sha256"])[0]
        rec["harness_sha256"][k] = "0" * 64
    v = evaluate(edit("project-state-machine.json", record_fn=r))
    assert v["verdict"] == "INVALID" and vals(v)["V3"] is True


def test_wrong_protocol_hash_is_invalid(base, edit):
    v = evaluate(edit("git-traceability.json", record_fn=lambda r: r.update(protocol_freeze_hash="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_wrong_prereg_hash_is_invalid(base, edit):
    v = evaluate(edit("git-traceability.json", record_fn=lambda r: r.update(engine_prereg_sha256="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_disagreeing_provenance_is_invalid(base, edit):
    v = evaluate(edit("baseline-comparison.json", record_fn=lambda r: r.update(seed=999)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


def test_evidence_naming_a_different_engine_version_is_invalid(base, edit):
    v = evaluate(edit("baseline-comparison.json", record_fn=lambda r: r.update(engine_version="1.0")))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


def test_oracle_that_imports_the_runtime_means_the_project_graded_itself(base, edit):
    v = evaluate(edit("project-state-machine.json", lambda p: p["oracle"]["oracle_import_audit"].update(independent=False, forbidden=["world.py: eoo_engine"])))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V4"]


def test_authoritative_verdict_not_reproducible_blocks_support(base, edit):
    def f(p):
        p["authoritative"]["reproducible"] = False
    v = evaluate(edit("verdict-reproducibility.json", f))
    assert vals(v)["S2"] is False and v["verdict"] != "SUPPORTED"


def test_ontology_only_write_blocks_support(base, edit):
    def f(p):
        p["cases"][0]["steps"][0]["eoo"]["unchanged"] = False
    v = evaluate(edit("project-state-machine.json", f))
    assert vals(v)["S3"] is False and v["verdict"] != "SUPPORTED"


def test_untraced_commit_blocks_support(base, edit):
    def f(p):
        p["cases"][0]["steps"][0]["eoo"]["trace"] = False
    v = evaluate(edit("project-state-machine.json", f))
    assert vals(v)["S3"] is False


def test_summary_that_disagrees_with_the_rows_is_a_problem(base, edit):
    v = evaluate(edit("project-state-machine.json", lambda p: p["eoo"].update(illegal_accepted=5)))
    assert v["problems"] and v["verdict"] != "SUPPORTED"


def test_missing_evidence_never_supports(edit):
    v = evaluate(edit(drop="mutation-results.json"))
    assert v["verdict"] != "SUPPORTED" and any("mutation-results.json: missing" in p for p in v["problems"])


def test_tampered_payload_never_supports(positive_dir, tmp_path):
    import json, shutil
    dst = tmp_path / "t"
    shutil.copytree(positive_dir, dst)
    rec = json.loads((dst / "mutation-results.json").read_text())
    rec["payload"]["mutants"][0]["killed"] = False  # hash NOT refreshed
    (dst / "mutation-results.json").write_text(json.dumps(rec))
    v = evaluate(dst)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])
