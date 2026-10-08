"""The generic constitutional procedure (PROT-H25 s2): an event-sourced CaseBook over a compiled `GovIR`.

State is DERIVED from commit-ordered events (the governance marks are the durable record; paladin.core_g3 rebuilds the
book from them at restart). Judgments are opaque facts `(judge, value)`; `merit` is never stored here. A stage that lacks
judgments is AWAITING (None) unless the matter declares a lapse. No decision path below names a domain, model, body or
principal: ids are opaque keys into the document.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from paladin.govir import DECLARE, GovIR, conflict, decide_bodies

ALLOW, DENY, UPHELD, OVERTURNED = "ALLOW", "DENY", "UPHELD", "OVERTURNED"


@dataclass
class Case:
    id: str
    requester: str
    obo: str | None
    op: str
    args: dict | None
    refs: tuple
    seq: int
    tick: int
    judgments: list = field(default_factory=list)   # {"stage","judge","value","rid","seq"} in commit order
    appeal: dict | None = None                       # {"by","seq","tick"}
    decided: dict = field(default_factory=lambda: {"decision": None, "review": None})  # stage -> (outcome, seq, tick, how)
    executed: dict | None = None                     # stored {"status","body"} of the one execution
    ended: bool = False                              # emergency declare case: end() applied


class CaseBook:
    def __init__(self, g: GovIR, mutants=frozenset()):
        self.g, self.mutants = g, frozenset(mutants)
        self.cases: dict[str, Case] = {}
        self.order: list[str] = []

    # ---- structure of a case under the document in force -----------------------------------------
    def matters(self, c: Case) -> list:
        return self.g.covering(c.op, c.refs)

    def bodies(self, c: Case) -> tuple:
        bs, _m, st = decide_bodies(self.g, self.matters(c), self.mutants)
        return bs if st == "ok" else ()

    def governing(self, c: Case):
        ms = self.matters(c)
        _bs, m, st = decide_bodies(self.g, ms, self.mutants)
        return m if st == "ok" else None

    def eligible(self, c: Case, body_id: str) -> tuple:
        b = self.g.bodies[body_id]
        return tuple(m for m in b.members if not (b.recuse_requester and m == c.requester))

    def review_body(self, c: Case) -> str | None:
        m = self.governing(c)
        return m.review_by if m is not None else None

    def seers(self, c: Case) -> set:
        """Callers who see the case (PROT-H26 s1.3): requester, members of every competent and reviewing body."""
        out = {c.requester}
        for m in self.matters(c):
            for b in list(m.competent) + ([m.review_by] if m.review_by else []):
                out |= set(self.g.bodies[b].members)
        return out

    # ---- stage outcomes from judgments --------------------------------------------------------------
    def counted(self, c: Case, stage: str, body_id: str, upto: int | None = None) -> dict:
        elig, out = set(self.eligible(c, body_id)), {}
        for j in c.judgments:
            if j["stage"] == stage and j["judge"] in elig and j["judge"] not in out and (upto is None or j["seq"] <= upto):
                out[j["judge"]] = j
        return out

    def _body_outcome(self, c: Case, stage: str, body_id: str, upto=None):
        b, cnt = self.g.bodies[body_id], self.counted(c, stage, body_id, upto)
        pos, neg = ("concur", "dissent") if stage == "decision" else ("uphold", "overturn")
        n, k = len(self.eligible(c, body_id)), b.k
        if b.kind == "single":
            v = next((j["value"] for j in cnt.values()), None)
            return "+" if v == pos else "-" if v == neg else None
        if n < k:
            return None  # impossible quorum: AWAITING forever (s2.3)
        p = sum(j["value"] == pos for j in cnt.values())
        q = sum(j["value"] == neg for j in cnt.values())
        need = max(k - 1, 0) if (stage == "decision" and "quorum_weakened" in self.mutants) else k  # MUTANT quorum_weakened
        if p >= need:
            return "+"
        if stage == "decision" and q > n - k:
            return "-"
        if stage == "review" and q >= k:
            return "-"
        return None

    def stage_outcome(self, c: Case, stage: str, upto: int | None = None):
        """Judgment-derived outcome (ALLOW/DENY | UPHELD/OVERTURNED) or None = AWAITING."""
        if stage == "decision":
            bs = self.bodies(c)
            if not bs:
                return None
            outs = [self._body_outcome(c, "decision", b, upto) for b in bs]
            if len(bs) > 1 or self.matters(c)[0].concurrence:   # concurrence: all must allow, any deny denies
                return ALLOW if all(o == "+" for o in outs) else DENY if any(o == "-" for o in outs) else None
            return {"+": ALLOW, "-": DENY}.get(outs[0])
        rb = self.review_body(c)
        if rb is None or c.appeal is None:
            return None
        return {"+": UPHELD, "-": OVERTURNED}.get(self._body_outcome(c, "review", rb, upto))

    def lapse_due(self, c: Case, tick: int) -> str | None:
        m = self.governing(c)
        if m is not None and m.lapse is not None and tick >= c.tick + m.lapse_after:
            return ALLOW if m.lapse == "allow" else DENY
        return None

    # ---- the decided points (fixed at commit points) --------------------------------------------------
    def decision(self, c: Case, tick: int):
        """(outcome, seq, tick, how) of the decision stage as of `tick`, applying a due lapse lazily; None = AWAITING."""
        if c.decided["decision"] is not None:
            return c.decided["decision"]
        x = self.lapse_due(c, tick)
        # G3-E14(2): the lapse is fixed at propose_tick + after (pure logical time), not at the recording transaction
        return (x, None, c.tick + self.governing(c).lapse_after, "lapse") if x is not None else None

    def settle(self, seq: int, tick: int) -> None:
        """Fix every due lapse at THIS transaction (s2.5): called before an event is applied."""
        for c in self.cases.values():
            if c.decided["decision"] is None:
                d = self.decision(c, tick)
                if d is not None:
                    c.decided["decision"] = (d[0], seq, d[2], "lapse")

    def final(self, c: Case, tick: int):
        """(status, outcome, rule, stages) status in FINAL | AWAITING | NOT_FINAL (s2.6)."""
        d = self.decision(c, tick)
        if d is None:
            return "AWAITING", None, None
        m = self.governing(c)
        if m is None or m.review_by is None:
            return "FINAL", d[0], "lapse" if d[3] == "lapse" else "decision"
        if c.appeal is None:
            if tick >= d[2] + m.window:
                return "FINAL", d[0], "lapse" if d[3] == "lapse" else "decision"
            return "NOT_FINAL", None, None
        r = c.decided["review"]
        if r is None:
            return "AWAITING", None, None
        out = d[0] if r[0] == UPHELD else (DENY if d[0] == ALLOW else ALLOW)
        return "FINAL", out, "review"

    def basis(self, c: Case, rule: str) -> list:
        out = []
        if rule != "lapse" and (c.decided["decision"] or (None,))[-1] != "lapse":
            for b in self.bodies(c):
                out += list(self.counted(c, "decision", b).values())
        if rule == "review" and self.review_body(c):
            out += list(self.counted(c, "review", self.review_body(c)).values())
        return [j["rid"] for j in sorted(out, key=lambda j: j["seq"])]

    # ---- applying committed events ---------------------------------------------------------------------
    def apply_propose(self, seq, tick, case, requester, obo, op, args, refs) -> Case:
        self.settle(seq, tick)
        c = self.cases[case] = Case(case, requester, obo, op, args, tuple(refs), seq, tick)
        self.order.append(case)
        return c

    def apply_judge(self, seq, tick, case, stage, judge, value, rid) -> None:
        self.settle(seq, tick)
        c = self.cases[case]
        c.judgments.append({"stage": stage, "judge": judge, "value": value, "rid": rid, "seq": seq})
        if c.decided[stage] is None:
            o = self.stage_outcome(c, stage)
            if o is not None:
                c.decided[stage] = (o, seq, tick, "judge")

    def apply_appeal(self, seq, tick, case, by) -> None:
        self.settle(seq, tick)
        self.cases[case].appeal = {"by": by, "seq": seq, "tick": tick}

    def apply_end(self, seq, tick, case) -> None:
        self.settle(seq, tick)
        self.cases[case].ended = True

    def apply_governance(self, seq, tick, g: GovIR) -> None:
        """set_governance: no grandfathering (Q14) - every open case is re-evaluated under the new document from here."""
        self.settle(seq, tick)
        self.g = g
        for c in self.cases.values():
            for stage in ("decision", "review"):
                o = self.stage_outcome(c, stage)
                cur = c.decided[stage]
                if o is None:
                    lap = self.lapse_due(c, tick) if stage == "decision" else None
                    c.decided[stage] = (lap, seq, c.tick + self.governing(c).lapse_after, "lapse") if lap is not None else None
                elif cur is None or cur[0] != o or cur[3] == "lapse":
                    c.decided[stage] = (o, seq, tick, "judge")

    # ---- emergencies (s3.5) ------------------------------------------------------------------------------
    def emergency(self, eid: str, tick: int):
        """The declare case of an emergency that is ACTIVE (final ALLOW, not ended) at `tick`, else None."""
        for cid in self.order:
            c = self.cases[cid]
            if c.op == DECLARE and isinstance(c.args, dict) and c.args.get("emergency") == eid and not c.ended:
                st, out, _rule = self.final(c, tick)
                if st == "FINAL" and out == ALLOW:
                    return c
        return None

    def conflicting(self, op: str, refs) -> bool:
        return conflict(self.g.covering(op, refs))
