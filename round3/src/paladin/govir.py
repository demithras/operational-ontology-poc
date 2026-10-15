"""Governance document -> typed control-plane relations (PROT-H25 s1/s2.1-2.2). The compile step of the EOO architecture.

The r3-governance-1 document is DATA. `compile_governance` turns it into one immutable `GovIR` (bodies, matters, the
transitive superior relation, the precedence list); the single generic evaluator (`paladin.procedure`) runs on it for
every model on both domains. Nothing in this module (or the evaluator) names a domain, a model id, a body id or a
principal id: those are opaque strings read from the document (R25-6, author decision 1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from r3_shared.authgraph import scope_covers, scope_subset

DECLARE = "emergency:declare"


@dataclass(frozen=True)
class Body:
    id: str
    members: tuple
    kind: str            # "single" | "quorum"
    k: int
    recuse_requester: bool
    rank: int


@dataclass(frozen=True)
class Matter:
    id: str
    scope: dict
    competent: tuple
    concurrence: bool
    review_by: str | None
    window: int
    lapse: str | None    # "allow" | "deny" | None (= await)
    lapse_after: int


@dataclass(frozen=True)
class GovIR:
    version: str
    bodies: dict
    matters: tuple
    above: dict          # body -> frozenset of every body strictly above it (transitive)
    precedence: tuple
    emergency: dict | None

    def covering(self, op: str, refs: Iterable) -> list:
        refs = list(refs)
        return [m for m in self.matters if scope_covers(m.scope, op, refs)]


def compile_governance(doc: dict, version: str) -> GovIR:
    bodies = {}
    for b in doc["bodies"]:
        r = b["rule"]
        quorum = r["kind"] == "quorum"
        bodies[b["id"]] = Body(b["id"], tuple(b["members"]), r["kind"], r["k"] if quorum else 1,
                               quorum and "requester" in r.get("recuse", []), b["rank"])
    up: dict[str, set] = {}
    for lo, hi in doc["superior"]:
        up.setdefault(lo, set()).add(hi)

    def closure(x: str, seen=None) -> set:
        seen = set() if seen is None else seen
        for h in up.get(x, ()):
            if h not in seen:
                seen.add(h)
                closure(h, seen)
        return seen
    matters = []
    for m in doc["matters"]:
        rv, ab = m["review"], m["on_absent"]
        lapse = ab["lapse"] if isinstance(ab, dict) else None
        matters.append(Matter(m["id"], m["scope"], tuple(m["competent"]), m["concurrence"],
                              rv["by"] if rv else None, rv["window"] if rv else 0, lapse,
                              ab["after"] if isinstance(ab, dict) else 0))
    return GovIR(version, bodies, tuple(matters), {b: frozenset(closure(b)) for b in bodies}, tuple(doc["precedence"]),
                 doc["emergency"])


def conflict(ms: list) -> bool:
    return len({m.concurrence for m in ms}) > 1


def decide_bodies(g: GovIR, ms: list, mutants=frozenset()) -> tuple:
    """(deciding body ids, the matter that governs lapse/review, status). status "ok" | "unresolved" | "none".
    Concurrence: every competent body decides. Otherwise the precedence list narrows the (body, matter) candidates."""
    if not ms:
        return (), None, "none"
    if ms[0].concurrence:
        bs = sorted({b for m in ms for b in m.competent})
        return tuple(bs), ms[0], "ok"
    inv = "precedence_inverted" in mutants  # MUTANT: every criterion keeps the MINIMAL elements instead of the maximal
    cands = [(b, m) for m in ms for b in m.competent]
    for crit in g.precedence:
        if crit == "specialis":
            if inv:   # strict-subset instead of strict-superset elimination
                cands = [(b, m) for b, m in cands if not any(_strict(o.scope, m.scope) for _, o in cands)]
            else:
                cands = [(b, m) for b, m in cands if not any(_strict(m.scope, o.scope) for _, o in cands)]
        elif crit == "superior":
            if inv:
                cands = [(b, m) for b, m in cands if not any(b in g.above[o] for o, _ in cands)]
            else:
                cands = [(b, m) for b, m in cands if not any(o in g.above[b] for o, _ in cands)]
        elif crit == "rank":
            rs = [g.bodies[b].rank for b, _ in cands]
            best = min(rs) if inv else max(rs)
            cands = [(b, m) for b, m in cands if g.bodies[b].rank == best]
    left = sorted({b for b, _ in cands})
    if len(left) != 1:
        return tuple(left), None, "unresolved"
    return (left[0],), next(m for b, m in cands if b == left[0]), "ok"


def _strict(a: dict, b: dict) -> bool:
    """a is a strict superset of b (scope_subset(b, a) and not equal)."""
    return scope_subset(b, a) and not scope_subset(a, b)
