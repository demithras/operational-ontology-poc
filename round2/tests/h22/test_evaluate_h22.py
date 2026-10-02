"""H22 evaluator: real gate-closed run -> INCONCLUSIVE; known-positive; one known-negative per contract clause."""
import json
import shutil

import pytest
from conftest import ROOT, make_case, rewrite

from eoo_h22 import fairness, facts
from eoo_h22.evaluate import evaluate
from hdd.verdict import h22_gate


def V(d):
    v = evaluate(d)
    return v["verdict"], v


def test_real_run_is_inconclusive_through_the_domain_gate(real_run):
    verdict, v = V(real_run)
    assert verdict == "INCONCLUSIVE" and v["problems"] == []
    assert v["gate"] == {"real_domains": 2, "completed_blind_tasks": 0, "open": False}
    assert v["common"] == {"protocol_valid": True, "required_evidence_complete": True, "sample_sufficient": False, "reject_hit": False, "support_hit": False}
    assert v["numbers"]["candidate_d3_sources"] == [] and v["numbers"]["accounting_asymmetries"] == []


def test_every_contract_clause_has_a_named_predicate(real_run):
    v = evaluate(real_run)
    con = json.loads((ROOT / "hypotheses/h22/contract.json").read_text())["evaluator"]
    for k in ("support_if", "reject_if", "inconclusive_if", "invalid_if"):
        assert len(v["predicates"][k]) >= len(con[k]) - (1 if k == "support_if" else 0)
    ids = {r["id"] for rows in v["predicates"].values() for r in rows}
    assert ids == {"S1", "S2", "S3", "S4", "R1", "R2", "I1", "V1", "V2", "V3", "V4"}


def test_known_positive_is_supported(case):
    make_case(case)
    verdict, v = V(case)
    assert verdict == "SUPPORTED", v["predicates"]
    assert v["numbers"]["classes_supported_noninferior"] and len(v["numbers"]["classes_supported_noninferior"]) == 5


def test_gate_agrees_with_hdd_h22_gate():
    assert not h22_gate(2, 30) and not h22_gate(3, 29) and h22_gate(3, 30)


def test_two_domains_with_supporting_numbers_is_inconclusive_not_supported(case):
    make_case(case, domains=2)
    verdict, v = V(case)
    assert verdict == "INCONCLUSIVE" and v["gate"]["open"] is False
    assert [r["value"] for r in v["predicates"]["support_if"]][0] is False


def test_two_domains_with_rejecting_numbers_is_still_inconclusive(case):
    make_case(case, domains=2, ratio=0.95, slope=1.1, ci=(1.0, 1.2))
    assert V(case)[0] == "INCONCLUSIVE"


def test_fewer_than_30_tasks_is_inconclusive(case):
    make_case(case, tasks=29)
    assert V(case)[0] == "INCONCLUSIVE"


def test_synthetic_or_unevidenced_domain_is_not_counted(case):
    make_case(case)
    rewrite(case, "domain-manifest.json", lambda p: p["real_domains"][2].update(synthetic=True))
    verdict, v = V(case)
    assert verdict == "INCONCLUSIVE" and v["numbers"]["real_domain_count"] == 2
    make_case(case)
    rewrite(case, "domain-manifest.json", lambda p: p["real_domains"][2].update(evidence_it_is_real=[]))
    assert V(case)[1]["numbers"]["real_domain_count"] == 2


def test_stated_domain_count_is_not_trusted(case):
    make_case(case, domains=2)
    rewrite(case, "domain-manifest.json", lambda p: p.update(real_domain_count=3))
    verdict, v = V(case)
    assert verdict == "INCONCLUSIVE" and v["numbers"]["real_domain_count"] == 2 and v["numbers"]["stated_real_domain_count"] == 3


def test_tasks_from_unknown_domains_are_not_counted(case):
    make_case(case)
    rewrite(case, "blind-task-results.json", lambda p: [t.update(domain="D9") for t in p["tasks"][:5]])
    verdict, v = V(case)
    assert v["numbers"]["completed_blind_tasks"] == 25 and verdict == "INCONCLUSIVE"


def test_three_domains_all_ratios_at_least_090_is_rejected(case):
    make_case(case, ratio=0.95, slope=0.95, ci=(0.9, 1.0))
    verdict, v = V(case)
    assert verdict == "REJECTED" and v["predicates"]["reject_if"][0]["value"] is True


def test_baseline_with_equal_or_lower_slope_is_rejected(case):
    make_case(case, ratio=0.5, slope=1.0, ci=(0.95, 1.05))
    assert V(case)[0] == "REJECTED"


def test_r2_savings_disappear_under_fair_baseline_tooling(case):
    make_case(case, fair=False)
    verdict, v = V(case)
    assert verdict == "REJECTED" and v["predicates"]["reject_if"][1]["value"] is True


def test_r2_savings_that_cost_a_regression(case):
    make_case(case, regress=1)
    assert V(case)[0] == "REJECTED"
    make_case(case, noninf=False)
    assert V(case)[0] == "REJECTED"


def test_i1_uncertainty_spanning_support_and_reject_is_inconclusive(case):
    make_case(case, slope=0.7, ci=(0.5, 0.95))
    verdict, v = V(case)
    assert verdict == "INCONCLUSIVE" and v["numbers"]["uncertainty_spans_support_and_reject"] is True


def test_s2_needs_two_classes_s3_needs_the_slope_s4_needs_a_tier(case):
    make_case(case, class_ratio={"source_churn": 0.5, "new_relation_query": 0.5, "policy_composition": 0.8, "action_addition": 0.8, "interface_reuse": 0.8})
    assert V(case)[0] == "SUPPORTED"
    make_case(case, class_ratio={"source_churn": 0.5, "new_relation_query": 0.8, "policy_composition": 0.8, "action_addition": 0.8, "interface_reuse": 0.8})
    assert V(case)[0] == "INCONCLUSIVE"  # only 1 class <= 0.75, not all >= 0.90
    make_case(case, slope=0.8, ci=(0.78, 0.82))
    assert V(case)[0] == "INCONCLUSIVE"
    make_case(case, tier=False)
    assert V(case)[0] == "INCONCLUSIVE"


def test_v1_corpus_metric_or_baseline_changed_after_reveal_is_invalid(case):
    make_case(case)
    h = {"corpus_sha256": "a", "cost_metric_sha256": "b", "baseline_sha256": "c"}
    rewrite(case, "blind-task-results.json", lambda p: p.update(reveal=h, current_hashes=dict(h)))
    assert V(case)[0] == "SUPPORTED"
    for k in h:
        rewrite(case, "blind-task-results.json", lambda p, k=k: p["current_hashes"].update({k: "changed"}))
        assert V(case)[0] == "INVALID"
        rewrite(case, "blind-task-results.json", lambda p: p.update(current_hashes=dict(h)))


def test_v2_a_null_glue_component_is_invalid(case):
    make_case(case)
    rewrite(case, "adaptation-costs.json", lambda p: p["per_task"][0]["baseline_components"].update(glue=None))
    verdict, v = V(case)
    assert verdict == "INVALID" and v["numbers"]["accounting_asymmetries"]
    make_case(case)
    rewrite(case, "adaptation-costs.json", lambda p: p["per_task"][1]["eoo_components"].pop("glue"))
    assert V(case)[0] == "INVALID"


def test_v3_wrong_protocol_hash_is_invalid(case):
    for f in ("domain-manifest.json",):
        r = json.loads((case / f).read_text())
        r["protocol_freeze_hash"] = "0" * 64
        (case / f).write_text(json.dumps(r))
    assert V(case)[0] == "INVALID"


def test_v4_disagreeing_provenance_is_invalid(case):
    r = json.loads((case / "trend-analysis.json").read_text())
    r["seed"] = 999
    (case / "trend-analysis.json").write_text(json.dumps(r))
    assert V(case)[0] == "INVALID"


def test_missing_evidence_never_supports(case):
    make_case(case)
    for f in ("trend-analysis.json", "tradeoff-frontier.md", "runtime-tax.json"):
        d2 = case.parent / ("m_" + f)
        shutil.copytree(case, d2)
        (d2 / f).unlink()
        verdict, v = V(d2)
        assert verdict != "SUPPORTED" and v["problems"]


def test_tampered_payload_never_supports(case):
    make_case(case)
    r = json.loads((case / "trend-analysis.json").read_text())
    r["payload"]["slope_ratio"] = 0.1
    (case / "trend-analysis.json").write_text(json.dumps(r))
    verdict, v = V(case)
    assert verdict != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_context_facts_are_labelled_and_read_from_committed_evidence(real_run):
    rt = json.loads((real_run / "runtime-tax.json").read_text())["payload"]
    c = rt["context"]
    assert c["label"].startswith("CONTEXT, NOT TREND") and c["h18_recurring_complexity_loc"] == {"baseline": 39, "eoo": 2191}
    assert c == facts.context() | {"git_head_at_read": c["git_head_at_read"]}
    md = (real_run / "tradeoff-frontier.md").read_text()
    assert "STATUS: not-run" in md and "Context, not trend" in md
    for f in ("blind-task-results.json", "adaptation-costs.json", "correctness-security.json", "trend-analysis.json", "runtime-tax.json"):
        assert json.loads((real_run / f).read_text())["payload"]["status"] == "not-run"
