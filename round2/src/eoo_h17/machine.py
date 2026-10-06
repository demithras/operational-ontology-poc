"""RuleBasedStateMachine driving the REAL Engine and the independent oracle side by side.

Every rule is one ENGINE_PREREG H17 sequence class (read, function_call, propose, approve, deny, retry,
crash_restart, execute, observe_outcome, unauthorized, stale_or_invalid). After every step the world markers and
every execution's class must equal the oracle's; the first disagreement raises ``Mismatch(kind, ...)`` which
Hypothesis shrinks to a minimal counterexample.
"""
from __future__ import annotations

import json

import hypothesis.strategies as st
from hypothesis.stateful import initialize, precondition, rule

from eoo_engine import EngineError, SimulatedCrash
from eoo_exp.util import sha_text

from . import calls
from .drivers import MFG_LATER, new_driver
from .machine_core import Core, Mismatch, O  # noqa: F401 - re-exported for tests
from .scenarios import PROFILES, for_profile

CLASSES = ("read", "function_call", "propose", "approve", "deny", "retry", "crash_restart", "execute",
           "observe_outcome", "unauthorized", "stale_or_invalid")
P = st.integers(0, 999)


def make_machine(domain: str, sink: dict):
    """A machine class for one domain. ``sink`` collects {"records": [...], "failures": [...]} across examples."""

    class H17Machine(Core):
        DOMAIN = domain

        # ---- init ---------------------------------------------------------------------------
        @initialize(pick=P)
        def setup(self, pick):
            profs = PROFILES[domain]
            self.profile = profs[pick % len(profs)]
            self.drv = new_driver(domain, self.profile)
            self.steps.append(["init", self.profile])

        # ---- READ transitions ---------------------------------------------------------------
        @rule(pick=P)
        def read(self, pick):
            self._note("read", pick, writes=False)
            before = self.drv.marker()
            e, types = self.drv.engine, calls.read_targets(self.drv)
            t = types[pick % len(types)]
            keys = self.drv.ref_keys(t)
            if keys:
                e.get(t, keys[pick % len(keys)])
            e.dispatch("object_types", "list", t)
            self.orc.read()
            self._unchanged(before, f"read {t}", "read_effect")

        @rule(pick=P, variant=st.integers(0, 5), via_tool=st.booleans())
        def function_call(self, pick, variant, via_tool):
            fid, args, label = calls.make_call(self.drv, pick, variant)
            self._note("function_call", fid, args, via_tool, label, writes=False)
            before = self.drv.marker()
            try:
                if via_tool:
                    self.drv.engine.tool("planner-1" if domain == "manufacturing" else "researcher-1").call_function(fid, args)
                else:
                    self.drv.engine.call_function(fid, args)
            except EngineError:
                pass
            self.orc.function_call()
            self._unchanged(before, f"function {fid}({label})", "function_effect")


        @rule(pick=P, via_tool=st.booleans())
        def propose(self, pick, via_tool):
            scn = self._pick(pick, "ok", "approval")
            self._note("propose", scn.id, via_tool, classes=("propose",))
            self._do_propose(scn, via_tool)

        @precondition(lambda self: bool(for_profile(domain, self.profile, "approval")))
        @rule(pick=P, via_tool=st.booleans())
        def propose_for_approval(self, pick, via_tool):
            scn = self._pick(pick, "approval")
            self._note("propose_for_approval", scn.id, via_tool, classes=("propose",))
            self._do_propose(scn, via_tool)

        @rule(pick=P, via_tool=st.booleans())
        def unauthorized(self, pick, via_tool):
            scn = self._pick(pick, "unauthorized")
            self._note("unauthorized", scn.id, via_tool, classes=("unauthorized", "propose"))
            self._do_propose(scn, via_tool)

        @rule(pick=P, via_tool=st.booleans())
        def stale_or_invalid(self, pick, via_tool):
            scn = self._pick(pick, "invalid")
            self._note("stale_or_invalid", scn.id, via_tool, classes=("stale_or_invalid", "propose"))
            self._do_propose(scn, via_tool)

        @precondition(lambda self: any(p["scn"].key for p in self.props))
        @rule(pick=P, differ=st.booleans())
        def retry(self, pick, differ):
            keyed = [p for p in self.props if p["scn"].key]
            p = keyed[pick % len(keyed)]
            alt = differ and p["scn"].alt_inputs is not None
            self._note("retry", p["scn"].id, p["key"], alt)
            before = len(self.orc.execs)
            self._do_propose(p["scn"], False, alt=alt, key=p["key"], retry=True)
            if not alt and len(self.orc.execs) != before:
                self._fail("retry_not_idempotent", f"retry of {p['scn'].id} created a new execution")


        @precondition(lambda self: bool(self._pending()))
        @rule(pick=P, bad=st.booleans())
        def approve(self, pick, bad):
            self._note("approve", pick, bad)
            self._decide("approve", pick, bad)

        @precondition(lambda self: bool(self._pending()))
        @rule(pick=P, bad=st.booleans())
        def deny(self, pick, bad):
            self._note("deny", pick, bad)
            self._decide("reject", pick, bad)

        # ---- crash / recovery / outcome ------------------------------------------------------
        @rule(pick=P, ppick=P)
        def crash_restart(self, pick, ppick):
            scn = self._pick(pick, "ok", "approval", "unauthorized", "invalid")
            scn = scn if scn.key and not scn.clock else self._pick(0, "ok")  # clock scenarios cannot survive a restart
            full = scn.kind == "ok" and self.orc.mode == "ok"
            point = O.CRASH_POINTS[ppick % len(O.CRASH_POINTS)] if full else "PROPOSED"
            self._note("crash_restart", scn.id, point)
            self.n += 1
            key = f"k{self.n}"
            inputs, req = self._request(scn, key)
            e = self.drv.rebuild(faults={point})
            try:
                e.propose(scn.action, inputs, scn.principal, idempotency_key=key,
                          expected_versions=scn.expected_versions)
            except SimulatedCrash:
                pass
            else:
                self._fail("crash_point_not_reached", f"{scn.id}: no crash at {point}")
            xid = list(e.executions)[-1]
            self.drv.rebuild()
            self.xids.append(xid)
            self.props.append({"oid": self.orc.propose(req, crash=point), "scn": scn, "key": key})
            self._sync(f"crash {scn.id}@{point}")

        @rule()
        def execute(self):
            self._note("execute")
            self.drv.engine.recover()
            self.orc.recover()
            self._sync("recover")

        @precondition(lambda self: any(x.state != O.INFLIGHT for x in self.orc.execs))
        @rule(pick=P)
        def force_execute(self, pick):
            """Attack: execute an execution that is not approved (pending/denied/done/unknown) directly."""
            pool = [i for i, x in enumerate(self.orc.execs) if x.state != O.INFLIGHT]
            oid = pool[pick % len(pool)]
            self._note("force_execute", self.xids[oid], classes=("execute",))
            x = self.drv.engine.executions[self.xids[oid]]
            try:
                self.drv.engine.dispatch("actions", "execute", x["action"], execution=self.xids[oid])
            except EngineError:
                pass
            self.orc.force_execute(oid)
            self._sync(f"force_execute {self.xids[oid]}")

        @precondition(lambda self: bool(self.orc.execs))
        @rule(pick=P)
        def observe_outcome(self, pick):
            oid = pick % len(self.orc.execs)
            self._note("observe_outcome", self.xids[oid])
            try:
                self.drv.engine.reconcile(self.xids[oid])
            except EngineError:
                pass
            self.orc.observe_outcome(oid)
            self._sync(f"observe {self.xids[oid]}")

        @rule(pick=P)
        def adapter_fault(self, pick):
            mode = self.drv.MODES[pick % len(self.drv.MODES)]
            self._note("adapter_fault", mode, classes=("adapter_fault",), writes=False)
            self.drv.set_mode(mode)
            self.orc.set_mode(mode)

        def teardown(self):
            if self.drv is None:
                return
            body = [self.DOMAIN, self.profile, self.steps]
            rec = {"domain": domain, "profile": self.profile, "sha": sha_text(json.dumps(body, sort_keys=True, default=str)),
                   "n_steps": len(self.steps) - 1, "classes": sorted(c for c in self.cls if c in CLASSES),
                   "function_only": self.fn_only and len(self.steps) > 1}
            sink["records"].append(rec)
            if self.failed:
                sink["failures"].append(self.failed)

    H17Machine.__name__ = f"H17Machine_{domain}"
    return H17Machine
