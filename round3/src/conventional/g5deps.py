"""Gate 5 dependency tracking for the conventional service: the frozen dependency graph read as DATA, one circuit breaker and one
bulkhead per dependency node, and the explicit unavailability reply (PROT-H29 R29-6, R29-12).

Bulkhead rule: a node fault blocks ONLY the operations whose graph entry names that node. There is no "maintenance mode" and
no global flag; the `global_halt_on_fault` mutant (the one place that consults every breaker for every request) is the bug.
Breakers are driven by the logical clock. Cooldown is 0 ticks on purpose: every call after a failure is a half-open trial,
because the oracle classifies a request by the fault state AT ITS OWN TICK and a closed-for-N-ticks breaker would answer
UNAVAILABLE for a node that already recovered (spurious_unavailable, lost progress).
"""
from __future__ import annotations

import threading

from r3_shared.recovery import DEP_UNAVAILABLE
from r3_shared.variant import CallResult

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
COOLDOWN_TICKS = 0
BULKHEAD_SLOTS = 8


class Breaker:
    def __init__(self, cooldown: int = COOLDOWN_TICKS, threshold: int = 1):
        self.cooldown, self.threshold = cooldown, threshold
        self.state, self.failures, self.opened_at, self.seen = CLOSED, 0, None, False

    def allow(self, now: int) -> bool:
        """closed -> call; open -> call only as a half-open trial once the cooldown has passed."""
        if self.state == CLOSED:
            return True
        if now - self.opened_at >= self.cooldown:
            self.state = HALF_OPEN
            return True
        return False

    def success(self) -> None:
        self.state, self.failures, self.opened_at, self.seen = CLOSED, 0, None, True

    def failure(self, now: int) -> None:
        self.failures += 1
        self.seen = True
        if self.state == HALF_OPEN or self.failures >= self.threshold:
            self.state, self.opened_at = OPEN, now


class Bulkhead:
    """Bounded concurrent in-flight calls PER NODE: a slow dependency exhausts its own slots, never another node's."""

    def __init__(self, slots: int = BULKHEAD_SLOTS):
        self._sem = threading.BoundedSemaphore(slots)

    def __enter__(self):
        if not self._sem.acquire(blocking=False):
            raise BulkheadFull()
        return self

    def __exit__(self, *exc):
        self._sem.release()
        return False


class BulkheadFull(Exception):
    pass


class DepGraph:
    """The frozen dependency graph (r3-depgraph-1) as handed over by AuthorityBinding.graph. Data only."""

    def __init__(self, doc: dict):
        self.doc = doc

    def surface_of(self, domain: str, name: str | None) -> str:
        ops = self.doc["operations"]
        ent = ((ops.get(domain) or {}).get(name) or ops["*"].get(name)) if isinstance(name, str) else None
        return ent["surface"] if ent else "governed_mutation"

    def decision_nodes(self, domain: str, name: str | None = None, surface: str | None = None) -> list[str]:
        s = surface or self.surface_of(domain, name)
        return list(self.doc["surfaces"][s].get("decision", []))

    def outcome_nodes(self, domain: str, name: str) -> list[str]:
        ent = (self.doc["operations"].get(domain) or {}).get(name) or self.doc["operations"]["*"].get(name) or {}
        return list(ent.get("outcome", []))

    def system_nodes(self, domain: str) -> list[str]:
        """Every node of the domain's external systems (data: the graph's `systems` map)."""
        return sorted({n for ns in self.doc["systems"].get(domain, {}).values() for n in ns})


def unavailable(node: str) -> CallResult:
    return CallResult("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": node})


class Guard:
    """Per-node breakers + bulkheads + the descriptive dependency_status."""

    def __init__(self, graph: DepGraph, domain: str, clock, mutants=frozenset()):
        self.graph, self.domain, self._clock, self.mutants = graph, domain, clock, frozenset(mutants)
        nodes = ["AUTH", "ANCHOR", "OBS", *graph.system_nodes(domain)]
        self.breakers = {n: Breaker() for n in dict.fromkeys(nodes)}
        self.bulkheads = {n: Bulkhead() for n in self.breakers}

    def breaker(self, node: str) -> Breaker:
        if node not in self.breakers:
            self.breakers[node] = Breaker()
            self.bulkheads[node] = Bulkhead()
        return self.breakers[node]

    def up(self, node: str) -> None:
        self.breaker(node).success()

    def down(self, node: str) -> None:
        self.breaker(node).failure(self._clock.now())

    def allow(self, node: str) -> bool:
        return self.breaker(node).allow(self._clock.now())

    def tripped(self) -> str | None:
        """First node whose breaker is not closed (global_halt_on_fault mutant only)."""
        for n, b in self.breakers.items():
            if b.state != CLOSED:
                return n
        return None

    def status(self) -> dict:
        return {n: ("UNKNOWN" if not b.seen else ("UP" if b.state == CLOSED else "DOWN")) for n, b in sorted(self.breakers.items())}
