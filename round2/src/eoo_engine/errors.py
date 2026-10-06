"""Engine error types. Every refusal is explicit; nothing defaults to allow."""
from __future__ import annotations

from dataclasses import dataclass


class EngineError(Exception):
    """Base class for engine errors."""


@dataclass(frozen=True)
class Unbound:
    """A logic/adapter reference the IR needs but no domain pack supplied."""

    kind: str  # binding namespace, e.g. function / policy / precondition / adapter
    key: str  # the IR text / ref that needs a binding
    where: str  # IR location that needs it

    def __str__(self) -> str:
        return f"unbound {self.kind} {self.key!r} needed by {self.where}"


class LoadError(EngineError):
    """The package cannot be executed: invalid IR or unbound references (full list attached)."""

    def __init__(self, problems: list):
        self.problems = list(problems)
        super().__init__("; ".join(str(p) for p in self.problems[:20]) + (" ..." if len(self.problems) > 20 else ""))


class CapabilityError(EngineError):
    """A write or capability was attempted without a valid live grant / allowed request."""


class IntegrityError(EngineError):
    """A would-be state violates store integrity (types, keys, cardinality, references, staleness)."""


class InvalidRequest(EngineError):
    """A request is malformed (unknown resource, bad input types, missing idempotency key)."""


class SimulatedCrash(EngineError):
    """Raised by fault injection right after a journal record was durably written."""
