"""Shared plumbing of the H17 state machine: oracle bridge, world synchronisation, request/approval helpers."""
from __future__ import annotations

import json

from hypothesis.stateful import RuleBasedStateMachine

from eoo_engine import EngineError
from eoo_exp.util import load_oracle

from .drivers import MFG_LATER
from .scenarios import for_profile

O = load_oracle("h17", "model")
STATE_CLASS = {"DENIED": O.DENIED, "PENDING_APPROVAL": O.PENDING, "RECONCILED_SUCCESS": O.DONE,
               "OUTCOME_UNKNOWN": O.UNKNOWN, "PROPOSED": O.INFLIGHT, "APPROVED": O.INFLIGHT, "EXECUTING": O.INFLIGHT,
               "EFFECTS_COMMITTED": O.INFLIGHT, "RECONCILED_FAILED": "FAILED"}
GATE_NAME = {"fresh": "stale"}


class Mismatch(AssertionError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


class Core(RuleBasedStateMachine):
    """Helpers only (no rules). Subclasses set DOMAIN and SINK."""

    DOMAIN = ""

    def __init__(self):
        super().__init__()
        self.drv = None
        self.orc = O.World()
        self.steps, self.cls, self.props, self.xids = [], set(), [], []
        self.fn_only, self.failed, self.profile, self.n = True, None, None, 0

    # ---- plumbing -----------------------------------------------------------------------
    def _note(self, rule_name, *args, classes=(), writes=True):
        self.steps.append([rule_name, *args])
        self.cls.update(classes or (rule_name,))
        self.fn_only = self.fn_only and not writes

    def _fail(self, kind, detail):
        self.failed = {"kind": kind, "detail": detail, "domain": self.DOMAIN, "profile": self.profile,
                       "steps": [list(s) for s in self.steps]}
        raise Mismatch(kind, detail)

    def _sync(self, where: str):
        m, o = self.drv.marker(), self.orc
        if m["store"] != self.drv.store0 or o.canonical != 0:
            self._fail("canonical_changed", f"{where}: canonical store hash differs from its seed state")
        if m["effect_log"] != o.committed:
            self._fail("effect_log", f"{where}: EffectLog entries engine={m['effect_log']} oracle={o.committed}")
        if m["external"] != o.external:
            self._fail("external_effects", f"{where}: external effects engine={m['external']} oracle={o.external}")
        for oid, x in enumerate(o.execs):
            got = STATE_CLASS.get(self.drv.engine.executions[self.xids[oid]]["state"], "?")
            if got != x.state:
                self._fail("execution_class", f"{where}: exec {self.xids[oid]} engine={got} oracle={x.state}")

    def _unchanged(self, before: dict, where: str, kind: str):
        if self.drv.marker() != before:
            self._fail(kind, f"{where}: the world changed during a read-only transition")


    # ---- Action requests ----------------------------------------------------------------
    def _request(self, scn, key, alt=False):
        inputs = scn.alt_inputs if alt and scn.alt_inputs else scn.inputs
        intent = f"{scn.action}|{scn.principal}|{json.dumps(inputs, sort_keys=True)}"
        return inputs, O.Req(scn.action, intent, key if scn.key else None, scn.tokens, scn.n_effects)

    def _expect_gate(self, rec, oid, where):
        x = self.orc.execs[oid]
        if x.state == O.DENIED and x.denied_at:
            failed = [g["gate"] for g in rec["gates"] if not g["passed"]]
            want = GATE_NAME.get(x.denied_at, x.denied_at)
            if failed != [want]:
                self._fail("gate_mismatch", f"{where}: failed gates {failed}, oracle denies at {want!r}")

    def _do_propose(self, scn, via_tool, alt=False, key=None, retry=False):
        self.n += 1
        key = key or f"k{self.n}"
        inputs, req = self._request(scn, key, alt)
        if scn.clock:
            self.drv.clock["now"] = MFG_LATER
        try:
            if via_tool and scn.expected_versions is None:
                rec = self.drv.engine.tool(scn.principal).propose_action(
                    scn.action, inputs, idempotency_key=req.key)
            else:
                rec = self.drv.engine.propose(scn.action, inputs, scn.principal, idempotency_key=req.key,
                                              expected_versions=scn.expected_versions)
        finally:
            self.drv.clock["now"] = self.drv.NOW
        oid = self.orc.propose(req)
        if oid < len(self.xids):
            if rec["exec"] != self.xids[oid]:
                self._fail("retry_not_idempotent", f"{scn.id}: retry created {rec['exec']}, original {self.xids[oid]}")
        else:
            self.xids.append(rec["exec"])
            self.props.append({"oid": oid, "scn": scn, "key": key})
        self._expect_gate(rec, oid, scn.id)
        self._sync(f"propose {scn.id}")
        return rec

    def _pick(self, pick, *kinds):
        pool = for_profile(self.DOMAIN, self.profile, *kinds)
        return pool[pick % len(pool)]

    # ---- approval -----------------------------------------------------------------------
    def _pending(self):
        return [p for p in self.props if self.orc.execs[p["oid"]].state == O.PENDING]

    def _decide(self, op, pick, bad):
        pend = self._pending()
        p = pend[pick % len(pend)]
        scn, xid = p["scn"], self.xids[p["oid"]]
        who = (scn.approvers_bad if bad and scn.approvers_bad else scn.approvers_ok)[pick % len(
            scn.approvers_bad if bad and scn.approvers_bad else scn.approvers_ok)]
        ok = not (bad and scn.approvers_bad)
        try:
            getattr(self.drv.engine, op)(xid, who)
        except EngineError:
            if ok:
                self._fail("valid_approval_refused", f"{op} of {xid} by {who} was refused")
        getattr(self.orc, "approve" if op == "approve" else "reject")(p["oid"], ok)
        self._sync(f"{op} {xid} by {who}")
