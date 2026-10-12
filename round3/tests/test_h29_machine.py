"""The Hypothesis RuleBasedStateMachine (ORACLE-AND-HARNESS-G5 s3): runs, keeps the frozen vocabulary and the envelope bounds."""
from hypothesis import settings

from r3_harness.h29 import rules
from r3_harness.h29.machine import H29Machine, RULE_METHODS

TestMachine = H29Machine.TestCase
TestMachine.settings = settings(max_examples=25, stateful_step_count=14, deadline=None, database=None, derandomize=True)


def test_machine_rules_are_exactly_the_frozen_table():
    assert RULE_METHODS == set(rules.RULES)
