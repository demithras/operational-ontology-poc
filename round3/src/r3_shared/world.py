"""Ground-truth world store: one SQLite file per deployment.

Variants write ONLY through a WorldHandle scoped by writer name; meters read ONLY through WorldReader
(a read-only connection). Canonical truth is this file, never a variant's cache or log.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Callable

from .worldlog import LOG_SCHEMA, Tx

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
    def __init__(self, path: str | Path, clock=None, writers: frozenset[str] | None = None):
        self.path = str(path)
        self.clock = clock  # LogicalClock | None: read once per write transaction (tx.tick)
        self.writers = None if writers is None else frozenset(writers)
        con = _connect(self.path)
        con.execute("PRAGMA journal_mode=WAL")  # persistent in the file: every later connection is WAL
        con.executescript(SCHEMA + LOG_SCHEMA)
        con.commit()
        con.close()

    def handle(self, writer: str) -> "WorldHandle":
        if self.writers is not None and writer not in self.writers:
            raise ValueError(f"writer {writer!r} is not in the writer allowlist")
        return WorldHandle(self.path, writer, self.clock)

    def handle_factory(self) -> Callable[[str], "WorldHandle"]:
        return self.handle

    def reader(self) -> "WorldReader":
        return WorldReader(self.path)

    SEED_WRITER = "harness-seed"

    def seed(self, batches: list[list[dict]], writer: str = SEED_WRITER) -> list[int]:
        """P1e-8, HARNESS ONLY (the writer must be in the allowlist; add it only for H26 runs). Each batch is applied as ONE
        transaction tagged "seed" ending in one `seed` mark {"batch": i, "changes": n}, so paired worlds built from batch
        lists of equal shape (same change counts) have identical seq/tick schedules. A change is one of
        {"op":"create","type","key","props"} | {"op":"update","type","key","props"} | {"op":"delete","type","key"} |
        {"op":"link"|"unlink","link_type","src","dst"}. Returns the seq of each batch's seed mark."""
        h = self.handle(writer)
        seqs: list[int] = []
        try:
            for i, batch in enumerate(batches):
                with h.transaction(tag="seed") as tx:
                    for c in batch:
                        op = c["op"]
                        if op == "create":
                            h.create(c["type"], c["key"], c["props"])
                        elif op == "update":
                            h.update(c["type"], c["key"], c["props"])
                        elif op == "delete":
                            h.delete(c["type"], c["key"])
                        elif op in ("link", "unlink"):
                            getattr(h, op)(c["link_type"], c["src"], c["dst"])
                        else:
                            raise ValueError(f"unknown seed change op {op!r}")
                    seqs.append(tx.mark("seed", {"batch": i, "changes": len(batch)}))
        finally:
            h.close()
        return seqs


class WorldHandle:
    """Write+read access scoped by writer name. Autocommit per call; `transaction()` groups calls."""

    def __init__(self, path: str, writer: str, clock=None):
        self._clock = clock
        self._tx: Tx | None = None
        if not writer:
            raise ValueError("writer name required")
        self.writer = writer
        self._con = _connect(path, isolation_level=None, check_same_thread=False)  # PROT-H23-A8: callers may be threads; serialisation is the variant's job
        self._con.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        self._con.close()

    @contextmanager
    def transaction(self, tag: str | None = None):
        """One world write transaction (BEGIN IMMEDIATE). Yields a Tx; nested use raises RuntimeError."""
        if self._tx is not None:
            raise RuntimeError("nested world transaction")
        self._con.execute("BEGIN IMMEDIATE")
        try:
            self._con.execute("UPDATE world_meta SET v=v+1 WHERE k='tx'")
            tid = self._con.execute("SELECT v FROM world_meta WHERE k='tx'").fetchone()[0]
            tx = self._tx = Tx(self, tid, tag, self._clock.now() if self._clock is not None else 0)
            yield tx
        except BaseException:
            if self._con.in_transaction:
                self._con.execute("ROLLBACK")
            raise
        else:
            self._con.execute("COMMIT")
        finally:
            if self._tx is not None:
                self._tx._open = False
            self._tx = None

    @contextmanager
    def _scope(self):
        """The open Tx, or (autocommit write) a fresh single-write transaction with tag NULL."""
        if self._tx is not None:
            yield self._tx
        elif self._con.in_transaction:  # a caller opened a raw transaction on the connection (H23 leak test): join it
            self._con.execute("UPDATE world_meta SET v=v+1 WHERE k='tx'")
            tid = self._con.execute("SELECT v FROM world_meta WHERE k='tx'").fetchone()[0]
            yield Tx(self, tid, None, self._clock.now() if self._clock is not None else 0)
        else:
            with self.transaction() as tx:
                yield tx

    def _append(self, tx: Tx, kind: str, ref_: str, data: dict) -> int:
        cur = self._con.execute(
            "INSERT INTO world_log(tx,tag,tick,writer,kind,ref,data_json) VALUES(?,?,?,?,?,?,?)",
            (tx.id, tx.tag, tx.tick, self.writer, kind, ref_, _j(data)))
        return int(cur.lastrowid)

    # -- canonical writes (each also appends one world_log row in the same transaction) -----
    def create(self, type_: str, key: str, props: dict) -> int:
        with self._scope() as tx:
            try:
                self._con.execute("INSERT INTO canonical_objects VALUES(?,?,?,1)", (type_, key, _j(props)))
            except sqlite3.IntegrityError as exc:
                raise WorldConflict(f"{ref(type_, key)} exists") from exc
            self._append(tx, "create", ref(type_, key), {"props": props, "version": 1})
        return 1

    def update(self, type_: str, key: str, props: dict, expected_version: int | None = None) -> int:
        with self._scope() as tx:
            row = self._con.execute("SELECT props_json, version FROM canonical_objects WHERE type=? AND key=?",
                                    (type_, key)).fetchone()
            if row is None:
                raise WorldConflict(f"{ref(type_, key)} missing")
            if expected_version is not None and row[1] != expected_version:
                raise WorldConflict(f"{ref(type_, key)} version {row[1]} != expected {expected_version}")
            merged = {**json.loads(row[0]), **props}
            self._con.execute("UPDATE canonical_objects SET props_json=?, version=? WHERE type=? AND key=?",
                              (_j(merged), row[1] + 1, type_, key))
            self._append(tx, "update", ref(type_, key), {"patch": props, "props": merged, "version": row[1] + 1})
        return row[1] + 1

    def delete(self, type_: str, key: str) -> None:
        with self._scope() as tx:
            row = self._con.execute("SELECT props_json FROM canonical_objects WHERE type=? AND key=?",
                                    (type_, key)).fetchone()
            if row is None:
                raise WorldConflict(f"{ref(type_, key)} missing")
            self._con.execute("DELETE FROM canonical_objects WHERE type=? AND key=?", (type_, key))
            self._append(tx, "delete", ref(type_, key), {"props": json.loads(row[0])})

    def link(self, link_type: str, src: str, dst: str) -> None:
        with self._scope() as tx:  # a no-op re-link changes nothing and logs nothing
            n = self._con.execute("INSERT OR IGNORE INTO canonical_links VALUES(?,?,?)", (link_type, src, dst)).rowcount
            if n:
                self._append(tx, "link", "|".join((link_type, src, dst)), {"link_type": link_type, "src": src, "dst": dst})

    def unlink(self, link_type: str, src: str, dst: str) -> None:
        with self._scope() as tx:
            n = self._con.execute("DELETE FROM canonical_links WHERE link_type=? AND src=? AND dst=?",
                                  (link_type, src, dst)).rowcount
            if n:
                self._append(tx, "unlink", "|".join((link_type, src, dst)),
                             {"link_type": link_type, "src": src, "dst": dst})

    # -- external effect write (an adapter's committed effect on an outside system) ----------
    def external_write(self, adapter: str, target: str, payload: dict, idempotency_key: str | None = None) -> int:
        with self._scope() as tx:
            cur = self._con.execute(
                "INSERT INTO external_effects(adapter,target,payload_json,idempotency_key,writer) VALUES(?,?,?,?,?)",
                (adapter, target, _j(payload), idempotency_key, self.writer))
            eseq = int(cur.lastrowid)
            self._append(tx, "external", f"{adapter}:{target}#{eseq}",
                         {"adapter": adapter, "target": target, "payload": payload,
                          "idempotency_key": idempotency_key, "effect_seq": eseq})
        return eseq

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
        head = self._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0]
        return {"objects": objs, "links": links, "effects": _effects(self._con), "log_head": head}

    def log(self, after_seq: int = 0) -> list[dict]:
        """world_log rows with seq > after_seq, in seq order (data_json parsed into `data`)."""
        rows = self._con.execute("SELECT seq,tx,tag,tick,writer,kind,ref,data_json FROM world_log WHERE seq>? "
                                 "ORDER BY seq", (after_seq,)).fetchall()
        return [{"seq": s_, "tx": t, "tag": g, "tick": k, "writer": w, "kind": kd, "ref": r, "data": json.loads(d)}
                for s_, t, g, k, w, kd, r, d in rows]


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
