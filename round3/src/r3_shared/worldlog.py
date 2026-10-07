"""world_log support (PROTOCOL-P1d P1d-1): schema + the Tx object. Written only by WorldHandle, same SQLite txn."""
from __future__ import annotations

import json
from typing import Any

LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, tx INTEGER NOT NULL, tag TEXT,
  tick INTEGER NOT NULL, writer TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS world_meta(k TEXT PRIMARY KEY, v INTEGER NOT NULL);
INSERT OR IGNORE INTO world_meta VALUES('tx',0);
"""
KINDS = ("create", "update", "delete", "link", "unlink", "external", "mark")


def canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


class Tx:
    """Handle on one open world write transaction: id, tag, tick (clock read right after BEGIN IMMEDIATE)."""

    def __init__(self, handle, id_: int, tag: str | None, tick: int):
        self._h, self.id, self.tag, self.tick, self._open = handle, id_, tag, tick, True

    def mark(self, kind: str, payload: dict) -> int:
        """Append a `mark` row (ref = kind) in this transaction; returns its seq."""
        if not self._open:
            raise RuntimeError("transaction is closed")
        if not isinstance(kind, str) or not kind:
            raise ValueError("mark kind must be a non-empty string")
        return self._h._append(self, "mark", kind, payload)
