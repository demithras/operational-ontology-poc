"""Ground-truth world store: one SQLite file per deployment.

Variants write ONLY through a WorldHandle scoped by writer name; meters read ONLY through WorldReader
(a read-only connection). Canonical truth is this file, never a variant's cache or log.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_objects(
  type TEXT NOT NULL, key TEXT NOT NULL, props_json TEXT NOT NULL, version INTEGER NOT NULL,
  PRIMARY KEY(type, key));
CREATE TABLE IF NOT EXISTS canonical_links(
  link_type TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY(link_type, src, dst));
CREATE TABLE IF NOT EXISTS external_effects(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, adapter TEXT NOT NULL, target TEXT NOT NULL,
  payload_json TEXT NOT NULL, idempotency_key TEXT, writer TEXT NOT NULL);
"""


BUSY_MS = 15_000  # writers/handles: SQLite busy_timeout (WAL: writers queue behind one writer, readers never wait)
READ_WAIT_S = 20.0  # WorldReader: bounded total wait before the world is classified unreadable


class WorldLockTimeout(Exception):
    """The world store stayed locked/unreadable past the bounded wait (a leaked write transaction, a hung writer)."""


def _connect(target: str, **kw) -> sqlite3.Connection:
    con = sqlite3.connect(target, timeout=BUSY_MS / 1000, **kw)
    con.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    return con


def _is_lock(exc: sqlite3.OperationalError) -> bool:
    m = str(exc).lower()
    return "locked" in m or "busy" in m


def _j(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


class WorldConflict(Exception):
    """Write conflicts with current canonical state (exists / missing / stale version)."""


def ref(type_: str, key: str) -> str:
    return f"{type_}:{key}"


class WorldStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        con = _connect(self.path)
        con.execute("PRAGMA journal_mode=WAL")  # persistent in the file: every later connection is WAL
        con.executescript(SCHEMA)
        con.commit()
        con.close()

    def handle(self, writer: str) -> "WorldHandle":
        return WorldHandle(self.path, writer)

    def handle_factory(self) -> Callable[[str], "WorldHandle"]:
        return self.handle

    def reader(self) -> "WorldReader":
        return WorldReader(self.path)


class WorldHandle:
    """Write+read access scoped by writer name. Autocommit per call; `transaction()` groups calls."""

    def __init__(self, path: str, writer: str):
        if not writer:
            raise ValueError("writer name required")
        self.writer = writer
        self._con = _connect(path, isolation_level=None, check_same_thread=False)  # PROT-H23-A8: callers may be threads; serialisation is the variant's job
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._in_tx = False

    def close(self) -> None:
        self._con.close()

    def transaction(self):
        h = self

        class _Tx:
            def __enter__(self):
                h._con.execute("BEGIN IMMEDIATE")
                h._in_tx = True

            def __exit__(self, et, ev, tb):
                h._con.execute("COMMIT" if et is None else "ROLLBACK")
                h._in_tx = False
                return False

        return _Tx()

    # -- canonical writes -------------------------------------------------------------------
    def create(self, type_: str, key: str, props: dict) -> int:
        try:
            self._con.execute("INSERT INTO canonical_objects VALUES(?,?,?,1)", (type_, key, _j(props)))
        except sqlite3.IntegrityError as exc:
            raise WorldConflict(f"{ref(type_, key)} exists") from exc
        return 1

    def update(self, type_: str, key: str, props: dict, expected_version: int | None = None) -> int:
        row = self._con.execute("SELECT props_json, version FROM canonical_objects WHERE type=? AND key=?",
                                (type_, key)).fetchone()
        if row is None:
            raise WorldConflict(f"{ref(type_, key)} missing")
        if expected_version is not None and row[1] != expected_version:
            raise WorldConflict(f"{ref(type_, key)} version {row[1]} != expected {expected_version}")
        merged = {**json.loads(row[0]), **props}
        self._con.execute("UPDATE canonical_objects SET props_json=?, version=? WHERE type=? AND key=?",
                          (_j(merged), row[1] + 1, type_, key))
        return row[1] + 1

    def delete(self, type_: str, key: str) -> None:
        n = self._con.execute("DELETE FROM canonical_objects WHERE type=? AND key=?", (type_, key)).rowcount
        if n == 0:
            raise WorldConflict(f"{ref(type_, key)} missing")

    def link(self, link_type: str, src: str, dst: str) -> None:
        self._con.execute("INSERT OR IGNORE INTO canonical_links VALUES(?,?,?)", (link_type, src, dst))

    def unlink(self, link_type: str, src: str, dst: str) -> None:
        self._con.execute("DELETE FROM canonical_links WHERE link_type=? AND src=? AND dst=?", (link_type, src, dst))

    # -- external effect write (an adapter's committed effect on an outside system) ----------
    def external_write(self, adapter: str, target: str, payload: dict, idempotency_key: str | None = None) -> int:
        cur = self._con.execute(
            "INSERT INTO external_effects(adapter,target,payload_json,idempotency_key,writer) VALUES(?,?,?,?,?)",
            (adapter, target, _j(payload), idempotency_key, self.writer))
        return int(cur.lastrowid)

    # -- reads (variants may read their own truth) --------------------------------------------
    def get(self, type_: str, key: str) -> dict | None:
        r = self._con.execute("SELECT props_json, version FROM canonical_objects WHERE type=? AND key=?",
                              (type_, key)).fetchone()
        return None if r is None else {"props": json.loads(r[0]), "version": r[1]}

    def list(self, type_: str) -> list[dict]:
        rows = self._con.execute("SELECT key, props_json, version FROM canonical_objects WHERE type=? ORDER BY key",
                                 (type_,)).fetchall()
        return [{"key": k, "props": json.loads(p), "version": v} for k, p, v in rows]

    def links(self, link_type: str, src: str | None = None, dst: str | None = None) -> list[tuple[str, str]]:
        q, a = "SELECT src, dst FROM canonical_links WHERE link_type=?", [link_type]
        for col, val in (("src", src), ("dst", dst)):
            if val is not None:
                q += f" AND {col}=?"
                a.append(val)
        return [tuple(r) for r in self._con.execute(q + " ORDER BY src, dst", a).fetchall()]

    def external_effects(self) -> list[dict]:
        return _effects(self._con)


def _effects(con) -> list[dict]:
    rows = con.execute("SELECT seq,adapter,target,payload_json,idempotency_key,writer FROM external_effects "
                       "ORDER BY seq").fetchall()
    return [{"seq": s, "adapter": a, "target": t, "payload": json.loads(p), "idempotency_key": i, "writer": w}
            for s, a, t, p, i, w in rows]


class WorldReader:
    """Read-only connection (SQLite mode=ro): any write raises sqlite3.OperationalError."""

    def __init__(self, path: str):
        self._con = _connect(f"file:{path}?mode=ro", uri=True, isolation_level=None, check_same_thread=False)

    def close(self) -> None:
        self._con.close()

    def snapshot(self) -> dict:
        """One consistent read transaction (WAL: never blocked by an active writer). Bounded retry on lock errors;
        raises WorldLockTimeout when the world stays unreadable."""
        deadline, last = time.monotonic() + READ_WAIT_S, None
        while True:
            try:
                self._con.execute("BEGIN")
                try:
                    return self._snapshot()
                finally:
                    self._con.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                if not _is_lock(exc):
                    raise
                last = exc
                if self._con.in_transaction:
                    self._con.execute("ROLLBACK")
                if time.monotonic() >= deadline:
                    raise WorldLockTimeout(f"world unreadable for {READ_WAIT_S}s: {last}") from exc
                time.sleep(0.05)

    def _snapshot(self) -> dict:
        objs = {f"{t}:{k}": {"props": json.loads(p), "version": v} for t, k, p, v in self._con.execute(
            "SELECT type,key,props_json,version FROM canonical_objects ORDER BY type,key")}
        links = [list(r) for r in self._con.execute(
            "SELECT link_type,src,dst FROM canonical_links ORDER BY link_type,src,dst")]
        return {"objects": objs, "links": links, "effects": _effects(self._con)}


def diff(before: dict, after: dict) -> list[dict]:
    """Deterministic effect records between two snapshots, sorted by (kind order, ref)."""
    out: list[dict] = []
    bo, ao = before["objects"], after["objects"]
    for r in sorted(set(bo) | set(ao)):
        if r not in bo:
            out.append({"kind": "create", "ref": r, "props": ao[r]["props"]})
        elif r not in ao:
            out.append({"kind": "delete", "ref": r, "props": bo[r]["props"]})
        elif bo[r]["props"] != ao[r]["props"]:
            ch = {k: [bo[r]["props"].get(k), ao[r]["props"].get(k)]
                  for k in sorted(set(bo[r]["props"]) | set(ao[r]["props"]))
                  if bo[r]["props"].get(k) != ao[r]["props"].get(k)}
            out.append({"kind": "update", "ref": r, "changes": ch})
    bl, al = {tuple(x) for x in before["links"]}, {tuple(x) for x in after["links"]}
    out += [{"kind": "link", "ref": "|".join(x)} for x in sorted(al - bl)]
    out += [{"kind": "unlink", "ref": "|".join(x)} for x in sorted(bl - al)]
    seen = {e["seq"] for e in before["effects"]}
    out += [{"kind": "external", "ref": f"{e['adapter']}:{e['target']}#{e['seq']}", "payload": e["payload"],
             "writer": e["writer"], "idempotency_key": e["idempotency_key"]}
            for e in after["effects"] if e["seq"] not in seen]
    return out
