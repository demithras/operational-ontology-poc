"""Hypothesis RuleBasedStateMachine over the frozen rule table (ORACLE-AND-HARNESS-G5 s3): the PRIMARY role of Python Hypothesis for H29.
Rules are exactly rules.RULES (a test asserts the set equality with the generator's step kinds); @precondition guards implement the envelope
bounds; @invariant checks call the oracle's classifier after every step. Used for dev exploration against FakeHonest / the real variants and
for SHRINKING a falsifier hit (the shrunk trace is stored next to the raw sequence, never replacing it). The OFFICIAL corpus is the seeded
list of gen.py drawn from the same rule table (derandomize, database=None)."""
from __future__ import annotations

import random

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from r3_harness.h23.chooser import RandChooser
from r3_oracle import continuity as C

from . import faults, gen_draw, gen_emit as E, rules
from .gen_model import Plan


class H29Machine(RuleBasedStateMachine):
    DOMAIN = "manufacturing"

    def __init__(self):
        super().__init__()
        self.plan = Plan(self.DOMAIN)
        self.ch = RandChooser(random.Random(0))
        self.faulted = 0
        E.fill(self.plan, self.ch, 1, tag="warm")

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _live_windows(self):
        return [w for w in self.plan.windows if w["from_tick"] <= self.plan.t < w["to_tick"]]

    def _seeded(self, n):
        self.ch = RandChooser(random.Random(n))

    # ---- rules (one per frozen step kind) ------------------------------------------------------------------------
    @rule(n=st.integers(1, 3), s=st.integers(0, 10 ** 6))
    def advance(self, n, s):
        self.plan.advance(n)

    @rule(s=st.integers(0, 10 ** 6))
    def request(self, s):
        self._seeded(s)
        p = gen_draw.draw(self.plan, self.ch, "ok")
        if p is not None:
            E.request(self.plan, p)
        if s % 4 == 0:
            E.probe(self.plan, self.ch)                        # G5-E28 (a): an input-invalid probe is a `request` step (invalid_probe, probe_shape)

    @precondition(lambda self: E.healthy(self.plan))
    @rule(s=st.integers(0, 10 ** 6))
    def approve(self, s):
        self._seeded(s)
        E.approve_flow(self.plan, self.ch)

    @rule(s=st.integers(0, 10 ** 6))
    def delegate(self, s):
        self._seeded(s)
        who = gen_draw.principals(self.plan)[0]
        self.plan.add({"op": "delegate", "principal": who, "edge": {"id": "e-bad"}, "rid": self.plan.new_rid("d")})   # malformed: must not commit
        self.plan.note_send("request", None, None)

    @rule(s=st.integers(0, 10 ** 6))
    def revoke(self, s):
        self._seeded(s)
        who = gen_draw.principals(self.plan)[0]
        self.plan.add({"op": "revoke", "principal": who, "edge_id": "e-unknown", "rid": self.plan.new_rid("v")})
        self.plan.note_send("request", None, None)

    @rule(s=st.integers(0, 10 ** 6))
    def read(self, s):
        self._seeded(s)
        E.read(self.plan, gen_draw.any_read(self.plan, self.ch))

    @precondition(lambda self: any(q["kind"] == "request" and q.get("rid") for q in self.plan.sends))
    @rule(copies=st.integers(1, faults.REDELIVERY_MAX), concurrent=st.booleans())
    def redeliver(self, copies, concurrent):
        rid = next(q["rid"] for q in reversed(self.plan.sends) if q["kind"] == "request" and q.get("rid"))
        self.plan.add({"op": "redeliver", "rid": rid, "copies": copies, "concurrent": concurrent})

    @rule(k=st.integers(1, 3))
    def publish_authority(self, k):
        if k < len(self.plan.fam):
            E.publish(self.plan, k)

    @precondition(lambda self: len(self._live_windows()) < 2)
    @rule(node=st.sampled_from(["AUTH", "ANCHOR", "OBS"]), mode=st.sampled_from(rules.FAULT_MODES), d=st.integers(1, faults.PARTITION_MAX))
    def fault_start(self, node, mode, d):
        live = {w["node"] for w in self._live_windows()}
        if node not in live and len(live | {node} & {"AUTH", "ANCHOR", "OBS"}) < 3:
            self.plan.fault("F5", node, "drop" if node == "OBS" else mode, d)

    @precondition(lambda self: bool(self.plan.windows))
    @rule()
    def fault_heal(self):
        self.plan.heal(self.plan.windows[-1]["fid"])

    @precondition(lambda self: not self.plan.open_rec and len([1 for s in self.plan.steps if s["op"] == "crash"]) < faults.CRASHES_MAX)
    @rule(cp=st.sampled_from(faults.CRASH_POINTS[:3]), s=st.integers(0, 10 ** 6))
    def crash(self, cp, s):
        self._seeded(s)
        p = gen_draw.draw(self.plan, self.ch, "ok")
        if p is None:
            return
        rid = self.plan.new_rid("c")
        E.crash(self.plan, cp, rid)
        self.plan.advance(1)
        kt = self.plan.t
        E.request(self.plan, p, rid=rid, predict=cp != "CP1_before_commit")
        self.plan.advance(1)
        self.pending_kill = kt

    @precondition(lambda self: getattr(self, "pending_kill", None) is not None)
    @rule()
    def resume(self):
        E.resume(self.plan, self.pending_kill)
        self.pending_kill = None

    @precondition(lambda self: self.plan.open_rec)
    @rule()
    def recovery_schedule(self):
        E.recovery(self.plan)

    @precondition(lambda self: self.plan.open_rec is False and getattr(self, "pending_kill", None) is not None)
    @rule(what=st.sampled_from(rules.TAMPER_KINDS))
    def tamper(self, what):
        if not any(s["op"] == "tamper" for s in self.plan.steps):
            self.plan.add({"op": "tamper", "what": what})

    @rule()
    def dispatch(self):
        E.dispatch(self.plan)

    @precondition(lambda self: bool(self.plan.intents))
    @rule()
    def reconcile(self):
        E.reconcile(self.plan, sorted(self.plan.intents)[0])

    # ---- invariants (the oracle after every step) -----------------------------------------------------------------
    @invariant()
    def steps_are_frozen_vocabulary(self):
        for s in self.plan.steps:
            rules.validate_step(s)

    @invariant()
    def classifier_total(self):
        c = self.plan.classify("request", None, "x")
        assert c.kind in (C.SAFE, C.BLOCKED, C.UNRESOLVED)

    @invariant()
    def envelope_holds(self):
        ok, why = faults.envelope_ok({"steps": self.plan.steps})
        assert ok or "classes" in why, why          # composition of plain F5 faults is bounded by the preconditions


RULE_METHODS = {n for n in dir(H29Machine) if n in rules.RULES}
