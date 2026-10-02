"""Function-only audit and enumerated negative-Action results: clean on the real Engine, non-vacuous (known-negatives)."""
import pytest

from eoo_h17 import audits, mutants

DOMAINS = ("manufacturing", "project")


@pytest.mark.parametrize("domain", DOMAINS)
def test_function_only_traces_leave_effect_log_and_store_identical(domain):
    rows = audits.function_only_rows(domain, 3, 120)
    assert len({r["sha"] for r in rows}) > 80 and sum(r["function_calls"] for r in rows) > 100
    assert all(r["identical"] and r["effect_log_after"] == r["effect_log_before"] and r["store_equal"] and r["external_equal"] for r in rows)


def test_function_only_audit_known_negative_sees_a_function_that_writes():
    with mutants.function_writes_effect_log():
        rows = audits.function_only_rows("manufacturing", 3, 40)
    assert any(not r["identical"] and r["effect_log_after"] > r["effect_log_before"] for r in rows)
    with mutants.function_writes_store():
        rows = audits.function_only_rows("project", 3, 40)
    assert any(not r["store_equal"] for r in rows)


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_negative_case_has_zero_effects_and_the_expected_gate(domain):
    rows = audits.negative_rows(domain)
    assert len(rows) > 30 and all(r["zero_effects"] and r["effect_log_delta"] == 0 and r["external_delta"] == 0 for r in rows)
    assert all(r["failed_gates"] == [r["expected_gate"]] for r in rows if r["case"].startswith("denied"))
    kinds = {r["case"] for r in rows}
    assert {"denied:unauthorized", "denied:invalid", "denied:key_reuse_different_intent"} <= kinds
    assert {r["adapter_mode"] for r in rows} >= {"ok", "timeout"}


def test_manufacturing_unapproved_cases_are_covered_and_refused():
    rows = [r for r in audits.negative_rows("manufacturing") if r["case"].startswith("unapproved")]
    assert {r["case"] for r in rows} == {"unapproved:approve_bad", "unapproved:reject_ok", "unapproved:execute_while_pending"}
    assert all(r["zero_effects"] for r in rows)
    assert all(r["outcome"] != "returned" for r in rows if r["case"] != "unapproved:reject_ok")


def test_negative_audit_known_negative_sees_a_bypassed_gate():
    with mutants.bypass_authority_gate():
        rows = audits.negative_rows("manufacturing")
    assert any(not r["zero_effects"] for r in rows if r["kind"] == "unauthorized")
    with mutants.bypass_precondition_gate():
        rows = audits.negative_rows("project")
    assert any(not r["zero_effects"] for r in rows)
