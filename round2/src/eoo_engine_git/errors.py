"""Explicit, replayable refusals of the Git-backed store."""
from __future__ import annotations


class StoreError(Exception):
    pass


class RowRejected(StoreError):
    """A written row violates the package's generic integrity rules (undeclared property, bad type, immutable change...)."""

    def __init__(self, problems: list):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


class ConflictError(StoreError):
    """The head moved since the writer's base and the change cannot be replayed on it: nothing was written.

    ``conflicts`` is the replayable record: [{"path", "kind": property|file|integrity, "base", "ours", "theirs"}].
    """

    def __init__(self, base: str, head: str, conflicts: list):
        super().__init__(f"conflict: base {base[:10]} vs head {head[:10]}: "
                         + "; ".join(f"{c['path']}:{c.get('property', c['kind'])}" for c in conflicts))
        self.base, self.head, self.conflicts = base, head, list(conflicts)


class BatchError(StoreError):
    """The adapter cannot guarantee one commit for the whole action (payloads of its effects were not all announced)."""
