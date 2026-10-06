"""Evaluator: a known-positive evidence directory is SUPPORTED; for EACH clause a known-negative flips exactly that clause."""
import json

import pytest

from conftest import rewrite
from eoo_h21.evaluate import INCONCLUSIVE, INVALID, REJECT, SUPPORT, evaluate


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def flip(pos, fname, fn, verdict, expect_true=(), expect_false=()):
    rewrite(pos, fname, fn)
    v = evaluate(pos)
    got = vals(v)
    assert v["verdict"] == verdict, (v["verdict"], {k: x for k, x in got.items() if x is not (k.startswith("S"))})
    for k in expect_true:
        assert got[k] is True, (k, got)
    for k in expect_false:
        assert got[k] is False, (k, got)
    return v


def test_known_positive_is_supported(pos):
    v = evaluate(pos)
    assert v["verdict"] == "SUPPORTED", (v["problems"], vals(v))
    assert [k for k, x in vals(v).items() if x is not (k.startswith("S"))] == []
    n = v["numbers"]
    assert min(n["unique_cases"].values()) >= 10000 and n["conformance_rate"] == 1.0 and n["forbidden_effects"] == 0 and n["mutation_kill_rate"] == 1.0


def test_the_real_small_run_is_not_supported_below_the_frozen_sample(small_run):
    v = evaluate(small_run)
    assert v["verdict"] == "INCONCLUSIVE" and vals(v)["I1"] is True and vals(v)["S3"] is False


def test_every_contract_clause_has_a_named_predicate(small_run):
    from eoo_exp.util import ROOT
    c = json.loads((ROOT / "hypotheses/h21/contract.json").read_text())["evaluator"]
    v = evaluate(small_run)
    assert (len(c["support_if"]), len(c["reject_if"]), len(c["inconclusive_if"]), len(c["invalid_if"])) == (6, 1, 1, 1)  # the one inconclusive clause has two conditions (corpus size / polymorphism): I1 names both
    assert set(SUPPORT) == {"S1", "S2", "S3", "S4", "S5", "S6"} and set(REJECT) == {"R1"} and {"I1", "I2"} <= set(INCONCLUSIVE) and "V1" in INVALID
    assert {r["id"] for rows in v["predicates"].values() for r in rows} == set(SUPPORT) | set(REJECT) | set(INCONCLUSIVE) | set(INVALID)


def test_s1_r1_a_handwritten_endpoint_is_rejected(pos):
    flip(pos, "handwritten-diff.json", lambda p: p.update(handwritten_endpoint_or_tool_code_added=1), "REJECTED", ["R1"], ["S1"])


def test_s1_a_changed_toolchain_file_blocks_support_and_rejects(pos):
    flip(pos, "handwritten-diff.json", lambda p: p.update(toolchain_files_changed=["src/eoo_toolchain/gen_sdk.py"]), "REJECTED", ["R1"], ["S1"])


def test_s1_a_failed_end_to_end_demo_is_inconclusive(pos):
    def bad(p):
        p["end_to_end"]["all_ok"] = False
    flip(pos, "handwritten-diff.json", bad, "INCONCLUSIVE", ["I2"], ["S1"])


def test_s2_a_failed_conformance_check_blocks_support(pos):
    def bad(p):
        p["domains"]["project"]["conformance"]["passed"] -= 1
    v = flip(pos, "generated-surface-manifest.json", bad, "INCONCLUSIVE", [], ["S2"])
    assert v["numbers"]["conformance_rate"] < 1.0


def test_s2_the_regenerated_extended_surface_must_conform_too(pos):
    def bad(p):
        p["regenerated_conformance"]["passed"] -= 1
    flip(pos, "handwritten-diff.json", bad, "INCONCLUSIVE", [], ["S2"])


def test_s3_corpus_below_the_minimum_is_inconclusive(pos):
    def bad(p):
        p["domains"]["manufacturing"]["case_sha256"] = p["domains"]["manufacturing"]["case_sha256"][:9999]
    v = flip(pos, "security-differential.json", bad, "INCONCLUSIVE", ["I1"], ["S3"])
    assert v["numbers"]["unique_cases"]["manufacturing"] == 9999  # recomputed from the hashes, not from a summary field


def test_s3_duplicate_case_hashes_do_not_count_as_unique(pos):
    def bad(p):
        h = p["domains"]["project"]["case_sha256"]
        p["domains"]["project"]["case_sha256"] = h[:5000] + h[:5000] + h[:100]
    flip(pos, "security-differential.json", bad, "INCONCLUSIVE", ["I1"], ["S3"])


def test_s3_r1_an_overexposed_capability_is_rejected(pos):
    def bad(p):
        d = p["domains"]["project"]["differential"]
        d["mismatching_cases"], d["overexposed_total"] = 1, 1
    v = flip(pos, "security-differential.json", bad, "REJECTED", ["R1"], ["S3"])
    assert v["numbers"]["capability_equality"] < 1.0


def test_s3_an_underexposed_capability_blocks_support_without_rejecting(pos):
    def bad(p):
        d = p["domains"]["manufacturing"]["differential"]
        d["mismatching_cases"], d["underexposed_total"] = 1, 1
    flip(pos, "security-differential.json", bad, "INCONCLUSIVE", [], ["S3", "R1"])


def test_i3_engine_disagreement_is_inconclusive(pos):
    def bad(p):
        p["domains"]["project"]["engine_cross_check"]["disagreements"] = 2
    flip(pos, "security-differential.json", bad, "INCONCLUSIVE", ["I3"])


def test_s4_r1_a_forbidden_effect_is_rejected(pos):
    def bad(p):
        p["domains"]["manufacturing"]["totals"]["principals_with_effects"] = 1
    flip(pos, "agent-adversarial.json", bad, "REJECTED", ["R1"], ["S4"])


def test_s4_a_blind_effect_meter_is_inconclusive(pos):
    def bad(p):
        p["domains"]["project"]["positive_control"]["effect_observed"] = False
    flip(pos, "agent-adversarial.json", bad, "INCONCLUSIVE", ["I2"], ["S4"])


def test_s4_a_hidden_tool_that_exists_blocks_support(pos):
    def bad(p):
        p["domains"]["project"]["totals"]["unknown_tool"] -= 1
    flip(pos, "agent-adversarial.json", bad, "INCONCLUSIVE", [], ["S4"])


def test_s5_a_per_type_tool_blocks_support(pos):
    def bad(p):
        p["domains"]["project"][0]["tool_source_names_an_implementer"] = ["Hypothesis"]
    flip(pos, "interface-polymorphism.json", bad, "INCONCLUSIVE", [], ["S5"])


def test_s5_i1_polymorphism_not_implemented_is_inconclusive(pos):
    def bad(p):
        p["domains"]["project"] = [r for r in p["domains"]["project"] if r["interface"] != "VersionedResearchObject"]
    flip(pos, "interface-polymorphism.json", bad, "INCONCLUSIVE", ["I1"], ["S5"])


def test_s5_changed_tool_after_adding_implementers_blocks_support(pos):
    def bad(p):
        p["domains"]["manufacturing"][0]["after_adding_two_implementers"]["tool_source_identical"] = False
    flip(pos, "interface-polymorphism.json", bad, "INCONCLUSIVE", [], ["S5"])


def test_s6_a_surviving_mutant_blocks_support(pos):
    def bad(p):
        m = next(x for x in p["mutants"] if x["id"] == "suppress_allowed_action")
        m["per_domain"]["project"].update(conformance_failed=0, differential_mismatching_cases=0, polymorphism_failures=[])
    v = flip(pos, "mutation-results.json", bad, "INCONCLUSIVE", [], ["S6"])
    assert v["numbers"]["mutation_survivors"] == ["suppress_allowed_action"]  # recomputed from the per-domain check results


def test_s6_a_mutant_that_crashed_is_not_a_kill(pos):
    def bad(p):
        m = p["mutants"][0]
        m["harness_errors"] = {"project": "RuntimeError: boom"}
    flip(pos, "mutation-results.json", bad, "INCONCLUSIVE", ["I2"], ["S6"])


def test_v5_unclean_mutation_controls_invalidate(pos):
    def bad(p):
        p["controls"]["clean"] = False
    flip(pos, "mutation-results.json", bad, "INVALID", ["V5"])


def test_v1_toolchain_importing_the_oracle_is_invalid(pos):
    flip(pos, "generated-surface-manifest.json", lambda p: p["toolchain"].update(imports_oracle=True), "INVALID", ["V1"])


def test_v4_oracle_importing_the_engine_is_invalid(pos):
    flip(pos, "generated-surface-manifest.json", lambda p: p["oracle"][1].update(forbidden_imports=["eoo_engine"]), "INVALID", ["V4"])


def test_v4_a_changed_oracle_file_is_invalid(pos):
    flip(pos, "generated-surface-manifest.json", lambda p: p["oracle"][1].update(sha256="0" * 64), "INVALID", ["V4"])


def test_v2_wrong_protocol_hash_is_invalid(pos):
    rec = json.loads((pos / "mutation-results.json").read_text())
    rec["protocol_freeze_hash"] = "0" * 64
    (pos / "mutation-results.json").write_text(json.dumps(rec))
    v = evaluate(pos)
    assert v["verdict"] == "INVALID" and vals(v)["V2"] is True


def test_v3_disagreeing_provenance_is_invalid(pos):
    rec = json.loads((pos / "agent-adversarial.json").read_text())
    rec["git_commit"] = "deadbeef"
    (pos / "agent-adversarial.json").write_text(json.dumps(rec))
    assert vals(evaluate(pos))["V3"] is True


def test_v5_dirty_read_only_paths_are_invalid(pos):
    flip(pos, "handwritten-diff.json", lambda p: p.update(read_only_paths_dirty=[" M round2/domains/project/ir.json"]), "INVALID", ["V5"])


def test_missing_evidence_never_supports(pos):
    (pos / "agent-adversarial.json").unlink()
    v = evaluate(pos)
    assert v["verdict"] != "SUPPORTED" and v["problems"]


def test_tampered_payload_never_supports(pos):
    rec = json.loads((pos / "mutation-results.json").read_text())
    rec["payload"]["controls"]["clean"] = True
    rec["payload"]["mutants"] = []
    (pos / "mutation-results.json").write_text(json.dumps(rec))  # payload edited, hash NOT re-sealed
    v = evaluate(pos)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])
