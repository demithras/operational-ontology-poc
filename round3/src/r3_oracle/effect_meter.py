"""Per-call ground truth: the world-store diff around each call. Calls are sequential.

The meter reads ONLY the WorldReader snapshot. It never looks at CallResult (tests/test_oracle_independence.py
enforces this by AST scan: no import of r3_shared.variant and no use of `.status`/`.body` here).
"""
from __future__ import annotations

from r3_shared.world import WorldReader, diff


class EffectMeter:
    def __init__(self, reader: WorldReader):
        self._reader = reader
        self._before: dict | None = None

    def snapshot(self) -> dict:
        return self._reader.snapshot()

    def begin(self) -> dict:
        self._before = self._reader.snapshot()
        return self._before

    def end(self) -> list[dict]:
        if self._before is None:
            raise RuntimeError("end() without begin()")
        after = self._reader.snapshot()
        effects = diff(self._before, after)
        self._before = None
        return effects

    def measure(self, fn):
        """Run fn() between two snapshots; returns (fn's return value, measured effect records, before snapshot).
        The return value is passed through untouched and never interpreted here."""
        before = self.begin()
        try:
            ret = fn()
        finally:
            effects = self.end()
        return ret, effects, before
