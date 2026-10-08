"""Governance procedure (PROT-H25 s2): a generic evaluator over the governance DOCUMENT (policy as data, ruling Q1).

Pure: no I/O, no clock, no fixture vocabulary. The same code evaluates every model on both domains; nothing here
compares a domain name, model id, body id or principal id with a literal (R25-6). Discretionary merit never enters:
a judgment is (judge, value); `merit` is stored and returned by the service layer but never reaches this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from r3_shared.authgraph import scope_covers, scope_subset

AWAITING, ALLOW, DENY, UPHELD, OVERTURNED = "AWAITING", "ALLOW", "DENY", "UPHELD", "OVERTURNED"
BIG = 1 << 62  # "the transaction being committed right now" sorts after every stored judgment


@dataclass(frozen=True)
class Judgment:
    seq: int
    tick: int
    stage: str
    judge: str
    value: str
    rid: str


@dataclass
class Case:
    id: str
    requester: str
    obo: str | None
    operation: str
    args: dict
    seq: int
    tick: int
    judgments: list[Judgment] = field(default_factory=list)
    appeal: tuple[int, int, str] | None = None  # (seq, tick, by)
    executed: dict | None = None  # stored OK result of the (single) execution


@dataclass(frozen=True)
class Route:
    bodies: tuple[str, ...]
    concurrence: bool
    matter: dict  # the governing matter: first covering matter (document order) naming a deciding body


@dataclass(frozen=True)
class StageResult:
    outcome: str
    seq: int | None = None
    tick: int | None = None
    basis: tuple[str, ...] = ()
    lapsed: bool = False


@dataclass(frozen=True)
class Final:
    outcome: str  # ALLOW | DENY | AWAITING | NOT_FINAL
    rule: str | None = None
    basis: tuple[str, ...] = ()
    decision: StageResult | None = None
    review: StageResult | None = None


FirstTx = Callable[[int], "tuple[int, int] | None"]  # bound tick -> (seq, tick) of the first transaction with tick >= bound


class Procedure:
    def __init__(self, doc: dict, mutants: frozenset[str] = frozenset()):
        self.doc, self.mutants = doc, mutants
        self.bodies = {b["id"]: b for b in doc["bodies"]}
        self.matters = doc["matters"]
        self._above = self._closure(doc["superior"])

    @staticmethod
    def _closure(pairs) -> dict[str, set[str]]:
        up: dict[str, set[str]] = {}
        for lo, hi in pairs:
            up.setdefault(lo, set()).add(hi)
        out: dict[str, set[str]] = {}
        for b in list(up):
            seen, todo = set(), list(up[b])
            while todo:
                x = todo.pop()
                if x not in seen:
                    seen.add(x)
                    todo.extend(up.get(x, ()))
            out[b] = seen
        return out

    # -- routing (s2.1-2.2) ----------------------------------------------------------------------------
    def covering(self, op: str, resources) -> list[dict]:
        return [m for m in self.matters if scope_covers(m["scope"], op, resources)]

    def route(self, op: str, resources) -> Route | str:
        """Route or a refusal reason: not_governed | matter_conflict | precedence_unresolved."""
        cov = self.covering(op, resources)
        if not cov:
            return "not_governed"
        if len({m["concurrence"] for m in cov}) > 1:
            return "matter_conflict"
        cands: list[str] = []
        for m in cov:
            for b in m["competent"]:
                if b not in cands:
                    cands.append(b)
        if cov[0]["concurrence"]:
            return Route(tuple(cands), True, cov[0])
        for crit in self.doc["precedence"]:
            cands = self._keep(crit, cands, cov)
        if len(cands) != 1:
            return "precedence_unresolved"
        gov = next(m for m in cov if cands[0] in m["competent"])
        return Route((cands[0],), False, gov)

    def _keep(self, crit: str, cands: list[str], cov: list[dict]) -> list[str]:
        inv = "precedence_inverted" in self.mutants  # mutant: keep the MINIMAL elements
        if crit == "rank":
            ranks = {b: self.bodies[b]["rank"] for b in cands}
            tgt = min(ranks.values()) if inv else max(ranks.values())
            return [b for b in cands if ranks[b] == tgt]
        if crit == "superior":
            def beaten(b):  # a candidate strictly above (below, for the mutant) b
                return any((b in self._above.get(c, ())) if inv else (c in self._above.get(b, ()))
                           for c in cands if c != b)
            return [b for b in cands if not beaten(b)]
        if crit == "specialis":
            def general(b):  # every matter b is competent in is a strict superset of another candidate's matter
                mine = [m for m in cov if b in m["competent"]]
                return all(any(n is not m and any(c != b for c in n["competent"]) and self._strict(n["scope"], m["scope"])
                               for n in cov) for m in mine)
            return [b for b in cands if general(b) == inv]
        return cands

    @staticmethod
    def _strict(a: dict, b: dict) -> bool:
        return scope_subset(a, b) and not scope_subset(b, a)

    # -- eligibility (s2.3) ------------------------------------------------------------------------------
    def eligible(self, body: str, requester: str) -> list[str]:
        b = self.bodies.get(body)
        if b is None:
            return []
        rec = b["rule"].get("recuse", []) if b["rule"]["kind"] == "quorum" else []
        return [m for m in dict.fromkeys(b["members"]) if not ("requester" in rec and m == requester)]

    def need(self, body: str) -> int:
        r = self.bodies[body]["rule"]
        return 1 if r["kind"] == "single" else r["k"]

    # -- stages (s2.4-2.5) -------------------------------------------------------------------------------
    def _body_outcome(self, body: str, elig: list[str], votes: dict[str, str], yes: str, no: str) -> str:
        n, k = len(elig), self.need(body)
        if n < k:
            return AWAITING
        c = sum(v == yes for v in votes.values())
        d = sum(v == no for v in votes.values())
        weak = 1 if ("quorum_weakened" in self.mutants and self.bodies[body]["rule"]["kind"] == "quorum") else 0
        if c >= k - weak and c + d > 0:
            return ALLOW if yes == "concur" else UPHELD
        if yes == "concur" and d > n - k:
            return DENY
        if yes == "uphold" and d >= k:
            return OVERTURNED
        return AWAITING

    def _stage(self, case: Case, bodies: tuple[str, ...], stage: str, concurrence: bool,
               deadline: int | None = None) -> StageResult:
        yes, no = ("concur", "dissent") if stage == "decision" else ("uphold", "overturn")
        elig = {b: self.eligible(b, case.requester) for b in bodies}
        votes: dict[str, dict[str, str]] = {b: {} for b in bodies}
        counted: list[str] = []
        for j in (x for x in case.judgments if x.stage == stage and (deadline is None or x.tick < deadline)):
            hit = False
            for b in bodies:
                if j.judge in elig[b] and j.judge not in votes[b]:
                    votes[b][j.judge], hit = j.value, True
            if hit:
                counted.append(j.rid)
            outs = [self._body_outcome(b, elig[b], votes[b], yes, no) for b in bodies]
            res = self._combine(outs, concurrence)
            if res != AWAITING:
                return StageResult(res, j.seq, j.tick, tuple(counted))
        return StageResult(AWAITING, basis=tuple(counted))

    @staticmethod
    def _combine(outs: list[str], concurrence: bool) -> str:
        if not concurrence:
            return outs[0]
        if all(o in (ALLOW, UPHELD) for o in outs):
            return outs[0]
        bad = [o for o in outs if o in (DENY, OVERTURNED)]
        return bad[0] if bad else AWAITING

    def decision(self, case: Case, route: Route, now_tick: int) -> StageResult:
        absent = route.matter["on_absent"]
        if absent == "await":
            return self._stage(case, route.bodies, "decision", route.concurrence)
        deadline = case.tick + absent["after"]  # G3-E14(2): lapse is fixed in pure logical time
        res = self._stage(case, route.bodies, "decision", route.concurrence, deadline)
        if res.outcome == AWAITING and now_tick >= deadline:
            return StageResult(DENY if absent["lapse"] == "deny" else ALLOW, None, deadline, (), True)
        return res

    def review(self, case: Case, route: Route) -> StageResult:
        rv = route.matter["review"]
        if case.appeal is None or rv is None:
            return StageResult(AWAITING)
        return self._stage(case, (rv["by"],), "review", False)

    # -- final outcome (s2.6-2.7) --------------------------------------------------------------------------
    def final(self, case: Case, route: Route, now_tick: int) -> Final:
        dec = self.decision(case, route, now_tick)
        if dec.outcome == AWAITING:
            if "merit_autofill" in self.mutants:  # BUG: a missing judgment defaults to yes
                return Final(ALLOW, "decision", (f"autofill:{case.id}",), dec)
            return Final(AWAITING, None, (), dec)
        base_rule = "lapse" if dec.lapsed else "decision"
        rv = route.matter["review"]
        if rv is None:
            return Final(dec.outcome, base_rule, dec.basis, dec)
        if case.appeal is None:
            if now_tick >= dec.tick + rv["window"]:
                return Final(dec.outcome, base_rule, dec.basis, dec)
            return Final("NOT_FINAL", None, (), dec)
        rev = self.review(case, route)
        if rev.outcome == AWAITING:
            if "merit_autofill" in self.mutants:
                return Final(ALLOW, "review", (f"autofill:{case.id}",), dec, rev)
            return Final(AWAITING, None, (), dec, rev)
        out = dec.outcome if rev.outcome == UPHELD else (DENY if dec.outcome == ALLOW else ALLOW)
        return Final(out, "review", dec.basis + rev.basis, dec, rev)
