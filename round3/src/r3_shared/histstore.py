"""HistoryStore (variant-durable, mutable) and TamperView (harness-only attacker interface). PROTOCOL-P1d P1d-5.
Paladin/conventional import HistoryStore only; the import scan forbids TamperView there."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any

_SCHEMA = "CREATE TABLE IF NOT EXISTS hist(key TEXT PRIMARY KEY, value BLOB NOT NULL) WITHOUT ROWID"


def _open(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(_SCHEMA)
    return con


def _like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class _Base:
    def __init__(self, path: str):
        self._path, self._lock, self._con = str(path), threading.Lock(), _open(str(path))

    def close(self) -> None:
        self._con.close()

    def _keys(self, prefix: str) -> list[str]:
        with self._lock:
            return [r[0] for r in self._con.execute(
                "SELECT key FROM hist WHERE key LIKE ? ESCAPE '\\' ORDER BY key", (_like(prefix),))]

    def _get(self, key: str) -> bytes | None:
        with self._lock:
            r = self._con.execute("SELECT value FROM hist WHERE key=?", (key,)).fetchone()
        return None if r is None else bytes(r[0])

    def _put(self, key: str, value: bytes) -> None:
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("value must be bytes")
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO hist(key,value) VALUES(?,?)", (key, bytes(value)))

    def _delete(self, key: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM hist WHERE key=?", (key,))


class HistoryStore(_Base):
    """One SQLite file; key -> bytes, ordered by key, thread-safe, WAL. Overwrite allowed (mutable store)."""

    def put(self, key: str, value: bytes) -> None:
        self._put(key, value)

    def get(self, key: str) -> bytes | None:
        return self._get(key)

    def delete(self, key: str) -> None:
        self._delete(key)

    def keys(self, prefix: str = "") -> list[str]:
        return self._keys(prefix)


class TamperView(_Base):
    """Harness-only attacker view on the same file (own connection). Every primitive applied is recorded in log()."""

    def __init__(self, path: str):
        super().__init__(path)
        self._log: list[dict[str, Any]] = []

    def _rec(self, op: str, **kw) -> None:
        self._log.append({"op": op, **kw})

    def keys(self, prefix: str = "") -> list[str]:
        return self._keys(prefix)

    def read(self, key: str) -> bytes | None:
        return self._get(key)

    def write(self, key: str, value: bytes) -> None:
        self._put(key, value)
        self._rec("write", key=key, size=len(value))

    def delete(self, key: str) -> None:
        existed = self._get(key) is not None
        self._delete(key)
        self._rec("delete", key=key, existed=existed)

    def rename(self, old: str, new: str) -> None:
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                r = self._con.execute("SELECT value FROM hist WHERE key=?", (old,)).fetchone()
                if r is None:
                    raise KeyError(old)
                self._con.execute("DELETE FROM hist WHERE key=?", (old,))
                self._con.execute("INSERT OR REPLACE INTO hist(key,value) VALUES(?,?)", (new, r[0]))
                self._con.execute("COMMIT")
            except BaseException:
                if self._con.in_transaction:
                    self._con.execute("ROLLBACK")
                raise
        self._rec("rename", old=old, new=new)

    def log(self) -> list[dict]:
        return [dict(x) for x in self._log]
