"""Evaluator: known-positive -> SUPPORTED; for EACH reject / inconclusive / invalid clause a known-negative flips it."""
import json

import pytest

from eoo_h16.evaluate import evaluate

CLAUSES = ("S1", "S2", "S3", "S4", "S5", "R1", "R2", "R3", "I1", "I2", "I3", "V1", "V2", "V3", "V4")


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
    assert base["numbers"]["generated_unique_cases"] >= 2000 and base["numbers"]["requirements_total"] >= 50


def test_new_kernel_kind_is_rejected(base, edit):
    def f(p):
        p["snapshot"]["dispatch"]["handlers"]["quantities"] = {"handler": "X", "handler_kind_attr": "quantities", "operations": [], "handler_source_sha256": "0"}
    d = edit("kernel-after.json", f)
    v = evaluate(d)  # core-diff.json still says 0: the disagreement is reported, not trusted
    assert v["verdict"] == "REJECTED" and vals(v)["R1"] is True and vals(v)["S1"] is False
    assert any("core-diff.json new-kind count disagrees" in p for p in v["problems"])


def test_domain_branch_hit_is_rejected(base, edit):
    def f(p):
        h = {"file": "src/eoo_engine/x.py", "line": 1, "tokens": ["manufacturing"], "value": "manufacturing", "position": "compare"}
        p["scopes"]["engine_core"]["hits"].append(h)
        p["domain_identity_branches"] += 1
    v = evaluate(edit("domain-branch-audit.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R2", "S2"], flipped(base, v)


def test_literal_only_hit_is_not_support_but_not_reject(base, edit):
    def f(p):
        p["scopes"]["ir_core"]["hits"].append({"file": "x.py", "line": 1, "tokens": ["Part"], "value": "Part", "position": "plain"})
    v = evaluate(edit("domain-branch-audit.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S2"]


def test_rename_invariance_broken_is_rejected(base, edit):
    def f(p):
        p["rename_invariance_real_domains"]["manufacturing"] = False
    v = evaluate(edit("domain-branch-audit.json", f))
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R3", "S2"]


def test_missing_requirement_is_inconclusive(base, edit):
    def f(p):
        p["domain2_requirement_coverage"]["requirements"][0]["ok"] = False
    v = evaluate(edit("core-diff.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I1", "S3"]


def test_too_few_cases_is_inconclusive(base, edit):
    def f(p):
        del p["cases"][1500:]
    v = evaluate(edit("mixed-domain-generated.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I2", "S5"]


def test_load_failure_in_generated_is_inconclusive(base, edit):
    def f(p):
        r = dict(p["cases"][0], sha="bad000", loaded=False, error="LoadError: x")
        p["cases"].append(r)
        p["failures"].append(r)
    v = evaluate(edit("mixed-domain-generated.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I3", "S5"], (flipped(base, v), v["problems"])


def test_surviving_mutant_blocks_support(base, edit):
    def f(p):
        p["mutants"][0]["killed"] = False
    v = evaluate(edit("mutation-results.json", f))
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S4"]


def test_dirty_mutation_control_is_invalid(base, edit):
    def f(p):
        p["controls"]["clean"] = False
    v = evaluate(edit("mutation-results.json", f))
    assert v["verdict"] == "INVALID" and "V3" in flipped(base, v) and vals(v)["V3"] is True


def test_wrong_protocol_hash_is_invalid(base, edit):
    v = evaluate(edit("kernel-before.json", record_fn=lambda r: r.update(protocol_freeze_hash="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_wrong_prereg_hash_is_invalid(base, edit):
    v = evaluate(edit("core-diff.json", record_fn=lambda r: r.update(engine_prereg_sha256="0" * 64)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_disagreeing_provenance_is_invalid(base, edit):
    v = evaluate(edit("core-diff.json", record_fn=lambda r: r.update(seed=999)))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


def test_changed_kernel_freeze_is_invalid(base, edit):
    def f(p):
        p["snapshot"]["kernel_resource_kinds"].append("quantities")
    v = evaluate(edit("kernel-before.json", f))
    assert v["verdict"] == "INVALID" and "V4" in flipped(base, v)


def test_working_tree_differs_from_head_is_invalid(base, edit):
    def f(p):
        p["working_tree"]["engine_core_working_tree_equals_head"] = False
    v = evaluate(edit("kernel-after.json", f))
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V3"]


@pytest.mark.parametrize("name", ["kernel-before.json", "kernel-after.json", "core-diff.json", "domain-branch-audit.json",
                                  "mixed-domain-generated.json", "mutation-results.json"])
def test_missing_evidence_never_supports(edit, name):
    v = evaluate(edit(drop=name))
    assert v["verdict"] in ("INCONCLUSIVE", "INVALID") and v["common"]["required_evidence_complete"] is False
    assert any(name in p and "missing" in p for p in v["problems"])


def test_tampered_payload_never_supports(edit):
    d = edit()
    rec = json.loads((d / "core-diff.json").read_text())
    rec["payload"]["new_kernel_primitive_kind_count"] = 7  # hash not refreshed
    (d / "core-diff.json").write_text(json.dumps(rec))
    v = evaluate(d)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_every_contract_clause_has_a_predicate(base):
    assert sorted(vals(base)) == sorted(CLAUSES)
    c = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "hypotheses/h16/contract.json").read_text())["evaluator"]
    assert len(base["predicates"]["support_if"]) >= len(c["support_if"])
    assert len(base["predicates"]["reject_if"]) >= len(c["reject_if"])
    assert len(base["predicates"]["inconclusive_if"]) >= len(c["inconclusive_if"])
    assert len(base["predicates"]["invalid_if"]) >= len(c["invalid_if"])
