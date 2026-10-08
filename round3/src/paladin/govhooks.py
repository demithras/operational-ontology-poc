"""Governance hooks for the two constitutional actions that commit EFFECTS (PROT-H25 s3.4 execute, s3.5 act).

The Core's effect commit (`Core._commit`) calls `before(tx, d)` inside the world transaction, before the Engine pipeline:
the procedural checks run at the commit tick and return the principal the Engine pipeline runs as, or raise Rollback with
the frozen refusal. `after` writes the `governance` mark in the same transaction; `post` applies the committed event to
the CaseBook once the transaction has committed. Frozen order: s3.4 / s3.5 (procedure first, then base authority, then
the PROT-H23 operation semantics = the Engine pipeline).
"""
from __future__ import annotations

from paladin.core_g2 import Rollback
from paladin.engine import Principal
from paladin.govir import DECLARE
from paladin.procedure import ALLOW, DENY
from r3_shared.authgraph import scope_covers
from r3_shared.constitutional import governance_mark
from r3_shared.variant import CallResult

EM_ROLE = "gov:emergency"


def refusal(status: str, reason: str) -> Rollback:
    return Rollback(CallResult(status, {"gate": "governance", "reason": reason}))


def final_gate(core, c, tick: int):
    """(rule, basis) of the case's FINAL ALLOW at `tick`, or Rollback with oracle_needed / not_final / case_denied."""
    st, out, rule = core.book.final(c, tick)
    if "merit_autofill" in core.mutants and st == "AWAITING":   # MUTANT merit_autofill: a missing judgment defaults to yes
        return "decision", []
    if st == "AWAITING":
        raise refusal("DENIED", "oracle_needed")
    if st == "NOT_FINAL":
        raise refusal("DENIED", "not_final")
    if out == DENY:
        raise refusal("DENIED", "case_denied")
    return rule, core.book.basis(c, rule)


class GovExec:
    """execute {case}: the requester carries a final ALLOW case through the normal operation pipeline."""

    def __init__(self, core, sub: str, case):
        self.core, self.sub, self.c, self.seq = core, sub, case, None
        self.rule = self.basis = None

    def before(self, tx, d: dict) -> Principal:
        core, c = self.core, self.c
        if c.executed is not None:                      # raced: another execution committed first
            raise Rollback(CallResult(c.executed["status"], dict(c.executed["body"])))
        self.rule, self.basis = final_gate(core, c, tx.tick)
        if core.base_denied(self.sub, c.obo, c.op, c.args, tx.tick, d):
            raise refusal("DENIED", "no_authority")
        return core.principal(self.sub, c.obo, c.op)

    def after(self, tx, res: CallResult) -> None:
        from paladin.core import plain  # noqa: PLC0415
        self.seq = tx.mark("governance", governance_mark("execute", case=self.c.id, rule=self.rule, basis=self.basis))
        self.stored = {"status": res.status, "body": plain(res.body)}
        self.core.ledger.put_meta(f"exec:{self.c.id}", self.stored)

    def post(self, tx) -> None:
        self.core.book.settle(self.seq, tx.tick)
        self.c.executed = self.stored


class GovAct:
    """act {emergency, operation, args}: an ACTIVE emergency replaces the case procedure for its grantees, scope, window."""

    def __init__(self, core, sub: str, a: dict, refs):
        self.core, self.sub, self.a, self.refs, self.seq = core, sub, a, refs, None
    late_schema = True

    def before(self, tx, d: dict) -> Principal:
        core, a, tick = self.core, self.a, tx.tick
        c = core.book.emergency(a["emergency"], tick)
        if c is None:
            raise refusal("DENIED", "emergency_inactive")
        if self.sub not in c.args["grantees"]:
            raise refusal("DENIED", "not_grantee")
        if not scope_covers(c.args["scope"], a["operation"], self.refs):
            raise refusal("DENIED", "out_of_emergency_scope")
        if tick >= c.args["expires_at"] and "emergency_no_expiry" not in core.mutants:   # MUTANT emergency_no_expiry
            raise refusal("DENIED", "emergency_expired")
        real = core.booted.principals[self.sub]
        if a["operation"] == DECLARE or not core.pre_authority(real, a["operation"], a["args"], deny_only=True):
            raise refusal("DENIED", "no_authority")
        if core.schema_problem(a["operation"], a["args"]) is not None:   # then PROT-H23 operation semantics: schema first
            raise refusal("INVALID", "schema")
        return core.booted.shadow[self.sub]

    def after(self, tx, res: CallResult) -> None:
        self.seq = tx.mark("governance", governance_mark("act", emergency=self.a["emergency"], operation=self.a["operation"],
                                                         args=self.a["args"]))

    def post(self, tx) -> None:
        self.core.book.settle(self.seq, tx.tick)
