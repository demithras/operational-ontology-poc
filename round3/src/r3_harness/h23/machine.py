"""Hypothesis RuleBasedStateMachine over a Deployment: shrinks any forbidden effect to a minimal sequence.

Same rules as the seeded corpus driver (rules.gen_step/exe), driven by hypothesis `data` instead of an RNG.
Build with make_machine(variant, domain, specs); run with unittest/pytest via `Machine.TestCase`.
"""
from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from . import approval_rules, crash_appr, crash_rules
from .chooser import HypChooser
from .corpus import new_env
from .rules import WEIGHTS, exe, gen_step

FAIL = ("forbidden_effect", "identity_expansion", "backstop_failure", "crash_duplicate_effect", "crash_state_mismatch",
        "crash_approval_lost", "crash_approval_reuse")


def make_machine(variant, domain: str, specs: dict, fail_on=FAIL):
    class Machine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.env = new_env(variant, domain, specs, "machine")
            self.attacker = None
            self.last: list[dict] = []

        @initialize(data=st.data())
        def pick_attacker(self, data):
            self.attacker = HypChooser(data).choice(self.env.agents())

        def _do(self, data, name):
            step = gen_step(self.env, HypChooser(data), self.attacker, name)
            self.last = exe(self.env, step)

        @rule(data=st.data())
        def legit(self, data):
            self._do(data, "legit")

        @rule(data=st.data())
        def hidden_tool(self, data):
            self._do(data, "hidden")

        @rule(data=st.data())
        def identity_injection(self, data):
            self._do(data, "ident")

        @rule(data=st.data())
        def on_behalf_of(self, data):
            self._do(data, "obo")

        @rule(data=st.data())
        def retarget(self, data):
            self._do(data, "retarget")

        @rule(data=st.data())
        def mutate_returned_body(self, data):
            self._do(data, "mutate_body")

        @rule(data=st.data())
        def replay(self, data):
            self._do(data, "replay")

        @rule(data=st.data())
        def replay_after_revoke(self, data):
            self._do(data, "replay_revoke")

        @rule(data=st.data())
        def bad_token(self, data):
            self._do(data, "badtoken")

        @rule(data=st.data())
        def toctou_args(self, data):
            self._do(data, "toctou")

        @rule(data=st.data())
        def approval_attack(self, data):
            from .approval_rules import RULES
            self._do(data, HypChooser(data).choice(RULES))

        @rule(data=st.data())
        def crash_before_commit(self, data):
            self._do(data, "crash_before")

        @rule(data=st.data())
        def crash_after_commit(self, data):
            self._do(data, "crash_after")

        @rule(data=st.data())
        def crash_between_requests(self, data):
            self._do(data, "crash_idle")

        @rule(data=st.data())
        def crash_with_approval(self, data):
            self._do(data, HypChooser(data).choice(crash_appr.RULES))

        @invariant()
        def no_forbidden_effects(self):
            bad = [(c["rule"], c["operation"], c["classes"]) for c in self.last
                   if any(k in fail_on for k in c["classes"])]
            assert not bad, f"effect outside the oracle's allowed set: {bad}"

        def teardown(self):
            self.env.close()

    assert set(WEIGHTS) == {"legit", "hidden", "ident", "obo", "retarget", "mutate_body", "replay",
                            "replay_revoke", "badtoken", "toctou", *approval_rules.RULES, *crash_rules.RULES, *crash_appr.RULES}
    return Machine
