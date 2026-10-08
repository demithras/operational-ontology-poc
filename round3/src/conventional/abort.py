"""Transaction abort carrying the refusal CallResult (raised inside a world transaction -> rollback)."""
from __future__ import annotations

from r3_shared.variant import CallResult


class _Abort(Exception):
    def __init__(self, status: str, body: dict):
        super().__init__(status)
        self.result = CallResult(status, body)
