"""R-6: approvals are durable and single-use across crashes. Correct fake passes; lost / double-consumed approvals are caught."""
import random

from r3_harness.h23 import crash_appr
from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.corpus import attack_sequence, load_specs, new_env
from tests.fakes.h23_fakes import FakeDep, FakeVariant

SPECS = load_specs()


class VolatileDep(FakeDep):
    approvals_volatile = True  # approvals live in memory only: lost by every crash


class DoubleConsumeDep(FakeDep):
    def _consume(self, akey):  # consumption is never made durable: a restart after an after_commit crash resurrects it
        self.approved[akey] -= 1


def _variant(dep_cls):
    class V(FakeVariant):
        def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
            return dep_cls("correct", domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=state_dir)
    return V("correct")


def _run(variant, rules, n=14, seed=21):
    calls = []
    for i in range(n):
        calls += attack_sequence(variant, SPECS, seed, i, rules)["calls"]
    return calls


def _cls(calls):
    out = {}
    for c in calls:
        for k in c["classes"]:
            out.setdefault(k, []).append(c["rule"])
    return out


def test_correct_fake_keeps_approvals_across_crashes_and_consumes_exactly_once():
    calls = _run(FakeVariant("correct"), list(crash_appr.RULES))
    labels = {c["rule"] for c in calls}
    assert set(crash_appr.REQUIRED) <= labels, sorted(set(crash_appr.REQUIRED) - labels)
    assert not _cls(calls), _cls(calls)
    armed = [c for c in calls if c["rule"].endswith(":armed")]
    assert armed and all(c["crash_triggered"] for c in armed)
    by = {r: [c for c in calls if c["rule"] == r] for r in labels}
    assert all(c["measured"] for c in by["crash_appr_before:replay-same"])
    assert all(not c["measured"] for c in by["crash_appr_before:replay-new"])
    assert all(c["measured"] for c in by["crash_appr_after:armed"])
    assert all(not c["measured"] for c in by["crash_appr_after:replay-same"] + by["crash_appr_after:replay-new"])


def test_approval_lost_across_a_crash_is_flagged():
    got = _cls(_run(_variant(VolatileDep), list(crash_appr.RULES)))
    assert "crash_approval_lost" in got and "crash_appr_before:replay-same" in got["crash_approval_lost"]
    assert "crash_approval_reuse" not in got


def test_approval_consumed_twice_across_a_crash_is_flagged():
    got = _cls(_run(_variant(DoubleConsumeDep), list(crash_appr.RULES)))
    assert "crash_approval_reuse" in got and "crash_appr_after:replay-new" in got["crash_approval_reuse"]
    assert "forbidden_effect" in got and "crash_approval_lost" not in got


def test_rule_degrades_when_the_ledger_is_not_quiet():
    env = new_env(FakeVariant("correct"), "manufacturing", SPECS, "r6")
    try:
        env.approvals["x"] = 1
        assert crash_appr.gen_step(env, RandChooser(random.Random(1)), env.agents()[0], "crash_appr_before") is None
    finally:
        env.close()
