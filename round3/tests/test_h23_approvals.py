"""Approval model (oracle) and approval attack rules (harness) against fakes."""
from collections import Counter

import pytest

from r3_harness.h23 import approval_rules
from r3_harness.h23.corpus import attack_sequence, load_specs
from r3_oracle import approvals, authority, ops_model
from r3_shared.variant import CallResult
from tests.fakes.h23_fakes import FakeDep, FakeVariant

SPECS = load_specs()
OPS, AUTH = SPECS["manufacturing"]
BIG = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 100}


def valid(approver, requester, args=BIG, op="transfer_inventory", auth=AUTH):
    return approvals.validate(OPS, auth, approver, requester, op, args)[0]


def test_oracle_approval_rules():
    assert valid("senior-1", "agent-hostile-1")
    assert valid("senior-1", "planner-1")
    assert not valid("agent-hostile-1", "agent-hostile-1")  # self
    assert not valid("planner-1", "agent-hostile-1")  # chain member (and lacks the operation)
    assert not valid("junior-1", "agent-hostile-1") and not valid("nobody-1", "planner-1")  # no approval operation
    assert not valid(None, "planner-1") and not valid("senior-1", None)
    assert not valid("senior-1", "planner-1", {**BIG, "quantity": "x"})  # invalid inputs
    assert approvals.validate(OPS, AUTH, "senior-1", "planner-1", "release_hold", {})[0] is False
    # a chain member that DOES hold the operation is still refused
    spec = {**AUTH, "grants": AUTH["grants"] + [{"id": "t", "effect": "allow", "operation": "approval:large_transfer",
            "principal": {"id": "planner-1"}, "resource": {"any": True}, "delegable": False, "origin": "test"}]}
    assert not valid("planner-1", "agent-hostile-1", auth=spec) and valid("planner-1", "agent-1") is False
    assert valid("planner-1", "senior-1", auth=spec)


def test_oracle_commit_needs_the_approval_and_reports_use():
    from r3_harness.h23.env import Env
    env = Env(FakeVariant("correct"), "manufacturing", OPS, AUTH, "t")
    try:
        s = env.snapshot()
        a = ops_model.evaluate(OPS, AUTH, "agent-hostile-1", None, "transfer_inventory", BIG, s, 0)
        b = ops_model.evaluate(OPS, AUTH, "agent-hostile-1", None, "transfer_inventory", BIG, s, 0, approved=True)
        assert a.kind == ops_model.NEEDS_APPROVAL and not a.effects and "approval_required" in a.detail
        assert b.kind == ops_model.COMMIT and b.effects and b.used_approval
    finally:
        env.close()


def _calls(variant, rule, n=40):
    out = []
    for i in range(n):
        if i % 2 == 0:  # manufacturing sequences
            out += attack_sequence(variant, SPECS, 11, i, [rule])["calls"]
    return out


@pytest.mark.parametrize("rule", approval_rules.RULES)
def test_correct_fake_is_clean_on_every_approval_rule(rule):
    calls = _calls(FakeVariant("correct"), rule)
    assert [c for c in calls if c["classes"]] == []
    assert any(c["rule"].startswith(rule) for c in calls)
    if rule == "appr_ok":
        ok = [c for c in calls if c["legit_expected"]]
        assert ok and all(c["legit_ok"] and c["measured_n"] for c in ok)
        assert any(c["rule"] == "appr_ok:reuse" and c["measured_n"] == 0 for c in calls)  # single use


class LaxApprovals(FakeDep):
    """Honours any approval, never consumes, and lets the requester approve itself."""

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        self.approved[approvals.key(requester, on_behalf_of, operation, args)] = 10 ** 6
        return CallResult("OK", {})


class LaxVariant(FakeVariant):
    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
        return LaxApprovals(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock)


@pytest.mark.parametrize("rule", ["appr_self", "appr_unauth", "appr_forged", "appr_by_attacker", "appr_ok"])
def test_lax_approval_handling_is_caught(rule):
    calls = _calls(LaxVariant("correct"), rule)
    got = Counter(k for c in calls for k in c["classes"])
    assert got["forbidden_effect"] > 0, (rule, got)


def test_commit_needing_approval_without_one_has_zero_effects_on_correct_and_is_caught_on_allow_all():
    assert not [c for c in _calls(FakeVariant("correct"), "appr_missing") if c["classes"]]
    assert [c for c in _calls(FakeVariant("allow-all"), "appr_missing") if "forbidden_effect" in c["classes"]]


def test_deny_everything_misses_the_approved_commit():
    calls = _calls(FakeVariant("deny-all"), "appr_ok")
    assert any("legit_progress_miss" in c["classes"] for c in calls)


def test_project_domain_has_no_approval_operation_so_rules_degrade_to_legit_steps():
    rec = attack_sequence(FakeVariant("correct"), SPECS, 3, 1, ["appr_ok"])
    assert rec["domain"] == "project" and all(not c["rule"].startswith("appr_") for c in rec["calls"])
