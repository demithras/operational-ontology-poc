"""Evaluator tests (H15 Phase 3): a known-positive directory is SUPPORTED; for every reject_if / inconclusive_if / invalid_if
clause a known-negative directory flips exactly that clause; missing or tampered evidence is never SUPPORTED."""
import json

import pytest

from eoo_h15.evaluate import evaluate

from evidence_fixture import build, positive, CLASSES


def pred(v, pid):
    return next(r["value"] for k in ("support_if", "reject_if", "inconclusive_if", "invalid_if") for r in v["predicates"][k] if r["id"] == pid)


def run(tmp_path, **kw):
    return evaluate(build(tmp_path / "e", **kw))


def test_known_positive_is_supported(tmp_path):
    v = run(tmp_path)
    assert v["verdict"] == "SUPPORTED", v["problems"]
    assert all(pred(v, p) is True for p in ("S1", "S2", "S3", "S4", "S5", "S6"))
    assert all(pred(v, p) is False for p in ("R1", "R2", "R3", "R4", "I1", "I2", "V1", "V2", "V3"))


def test_verdict_is_deterministic(tmp_path):
    a = evaluate(build(tmp_path / "a"))
    b = evaluate(build(tmp_path / "b"))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _set(path, value):
    def m(p):
        d = p
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return m


REJECTS = {
    "R1": _set(("real-domain-roundtrip.json", "project", "openpona", "equivalent"), False),
    "R2": _set(("generated-roundtrip.json", "surfaces", "openpona", "failed"), 1),
    "R2u": _set(("generated-roundtrip.json", "surfaces", "openpona", "unrepresentable"), 1),
    "R3tok": _set(("compiler-diff-metrics.json", "primitive_tokens", "new_primitive_tokens_required"), 1),
    "R3side": _set(("sidecar-audit.json", "indispensable_sidecar_count"), 1),
    "R4acc": _set(("ambiguity-corpus.json", "summary", "openpona", "declared_accepted"), 1),
    "R4inv": _set(("ambiguity-corpus.json", "summary", "openpona", "deletion_violations"), 1),
}


@pytest.mark.parametrize("name", sorted(REJECTS))
def test_each_reject_clause_flips(tmp_path, name):
    def m(p):
        if name == "R2":  # keep totals consistent: one case moves from ok to failed
            p["generated-roundtrip.json"]["surfaces"]["openpona"]["ok"] = 9999
        if name == "R2u":
            p["generated-roundtrip.json"]["surfaces"]["openpona"]["ok"] = 9999
        REJECTS[name](p)
    v = run(tmp_path, mutate=m)
    assert v["verdict"] == "REJECTED", (name, v["predicates"])
    assert pred(v, name[:2]) is True


def test_dsl_baseline_failure_is_not_a_reject(tmp_path):
    def m(p):
        p["generated-roundtrip.json"]["surfaces"]["dsl"]["ok"] = 9999
        p["generated-roundtrip.json"]["surfaces"]["dsl"]["failed"] = 1
    assert run(tmp_path, mutate=m)["verdict"] != "REJECTED"


def test_i1_too_few_generated_cases(tmp_path):
    def m(p):
        g = p["generated-roundtrip.json"]
        g["valid_cases"] = 9999
        g["generation"]["generated"] = 9999
        for s in g["surfaces"].values():
            s["ok"] = 9999
    v = run(tmp_path, mutate=m)
    assert v["verdict"] == "INCONCLUSIVE" and pred(v, "I1") is True and pred(v, "S2") is False


def test_i2_domain_not_encoded_completely(tmp_path):
    v = run(tmp_path, mutate=_set(("real-domain-roundtrip.json", "manufacturing", "openpona", "encoded_completely"), False))
    assert v["verdict"] == "INCONCLUSIVE" and pred(v, "I2") is True


def test_i2_registered_domain_absent(tmp_path):
    def m(p):
        del p["real-domain-roundtrip.json"]["project"]
    v = run(tmp_path, mutate=m)
    assert v["verdict"] == "INCONCLUSIVE" and pred(v, "I2") is True and pred(v, "S1") is False


def test_s5_not_every_declared_case_fails_closed(tmp_path):
    v = run(tmp_path, mutate=_set(("ambiguity-corpus.json", "summary", "openpona", "declared_fail_closed"), 43))
    assert v["verdict"] == "INCONCLUSIVE" and pred(v, "S5") is False


def test_s5_missing_ambiguity_class(tmp_path):
    v = run(tmp_path, mutate=_set(("ambiguity-corpus.json", "declared", "openpona", "classes_covered"), CLASSES[:1]))
    assert v["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("surface", ["openpona", "dsl"])
def test_s6_surviving_mutant_blocks_support(tmp_path, surface):
    def m(p):
        mu = p["mutation-results.json"]
        mu["summary"][surface]["kill_rate"] = 5 / 6
        next(x for x in mu["mutants"] if x["surface"] == surface)["killed"] = False
    v = run(tmp_path, mutate=m)
    assert v["verdict"] == "INCONCLUSIVE" and pred(v, "S6") is False


def test_s6_missing_target_class(tmp_path):
    def m(p):
        p["mutation-results.json"]["mutants"] = [x for x in p["mutation-results.json"]["mutants"] if x["class"] != "drop_version"]
    assert run(tmp_path, mutate=m)["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("field", ["protocol_freeze_hash", "gate0_combined_sha256", "candidate_combined_sha256"])
def test_protocol_hash_mismatch_is_invalid(tmp_path, field):
    v = run(tmp_path, prov_for=lambda f: {field: "0" * 64} if f == "generated-roundtrip.json" else {})
    assert v["verdict"] == "INVALID" and pred(v, "V1") is True


def test_records_disagreeing_on_seed_are_invalid(tmp_path):
    v = run(tmp_path, prov_for=lambda f: {"seed": 16} if f == "sidecar-audit.json" else {})
    assert v["verdict"] == "INVALID" and pred(v, "V2") is True


@pytest.mark.parametrize("what", ["control", "after_restore", "oracle"])
def test_harness_self_check_failure_is_invalid(tmp_path, what):
    def m(p):
        mu = p["mutation-results.json"]
        if what == "control":
            mu["controls"]["openpona"]["clean"] = False
        elif what == "after_restore":
            mu["controls"]["dsl"]["clean_after_restore"] = False
        else:
            mu["oracle_known_negatives"]["all_detected"] = False
    v = run(tmp_path, mutate=m)
    assert v["verdict"] == "INVALID" and pred(v, "V3") is True


@pytest.mark.parametrize("name", ["real-domain-roundtrip.json", "generated-roundtrip.json", "ambiguity-corpus.json",
                                  "sidecar-audit.json", "mutation-results.json", "compiler-diff-metrics.json"])
def test_missing_file_is_never_supported(tmp_path, name):
    v = run(tmp_path, drop=(name,))
    assert v["verdict"] == "INCONCLUSIVE" and v["problems"] and v["common"]["required_evidence_complete"] is False


def test_tampered_payload_is_never_supported(tmp_path):
    v = run(tmp_path, tamper="sidecar-audit.json")
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_unreadable_json_is_never_supported(tmp_path):
    d = build(tmp_path / "e")
    (d / "ambiguity-corpus.json").write_text("{not json")
    assert evaluate(d)["verdict"] != "SUPPORTED"


def test_inconsistent_totals_block_support(tmp_path):
    v = run(tmp_path, mutate=_set(("generated-roundtrip.json", "surfaces", "dsl", "ok"), 9990))
    assert v["verdict"] != "SUPPORTED"


def test_reject_wins_over_missing_evidence(tmp_path):
    v = run(tmp_path, mutate=_set(("real-domain-roundtrip.json", "project", "openpona", "equivalent"), False), drop=("mutation-results.json",))
    assert v["verdict"] == "REJECTED"


def test_empty_directory_is_not_supported(tmp_path):
    (tmp_path / "e").mkdir()
    assert evaluate(tmp_path / "e")["verdict"] == "INCONCLUSIVE"
