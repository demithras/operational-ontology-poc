"""Logical clock: integer ticks, injectable, never reads wall-clock time."""
from __future__ import annotations


class LogicalClock:
    def __init__(self, start: int = 0):
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("clock start must be a non-negative int")
        self._now = start

    def now(self) -> int:
        return self._now

    def advance(self, n: int = 1) -> int:
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ValueError("advance(n) needs a non-negative int")
        self._now += n
        return self._now
