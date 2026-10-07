"""Durable request ledger + approvals + authority-in-force: Paladin's answer to PROT-H23-A8 (crash safety, R5 after restart).

The EOO architecture keeps decisions in a write-ahead journal, not in process memory. This journal lives in `state_dir`
(its own SQLite file, synchronous=FULL) and follows a prepare / commit / finalize protocol:

  prepare(rid, fp, world_digest)  durable BEFORE any world write       (state PREPARED)
  <world commit through the Engine pipeline>
  finalize(rid, status, body)     durable AFTER the world commit       (state COMMITTED; claimed approvals consumed)
  abort(rid)                      the request refused / rolled back    (row removed; claimed approvals released)

A crash between the world commit and finalize leaves a PREPARED row. `recover(current_digest)` resolves it at restart by
comparing the world's digest with the digest taken at prepare time (the deployment serialises commits, so at most one
request is in doubt): changed -> the request committed (finalize); unchanged -> it never reached the world (abort).

`volatile=True` is the ledger_after_commit_volatile MUTANT: a plain in-memory dict written after the commit, lost on crash.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests(rid TEXT PRIMARY KEY, fp TEXT NOT NULL, state TEXT NOT NULL, pre TEXT,
  sub TEXT, obo TEXT, op TEXT, status TEXT, body_json TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, fp TEXT NOT NULL, approver TEXT NOT NULL,
  claimed_by TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class Ledger:
    def __init__(self, path: str, volatile: bool = False):
        self.volatile = volatile
        self._mem: dict[str, dict] = {}
        self._mem_appr: list[dict] = []
        self._con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._con.execute("PRAGMA synchronous=FULL")
        self._con.executescript(_SCHEMA)
        self._lock = threading.RLock()

    # ---- requests -----------------------------------------------------------------------------
    def get(self, rid: str) -> dict | None:
        with self._lock:
            if self.volatile:
                return self._mem.get(rid)
            r = self._con.execute("SELECT fp,state,sub,obo,op,status,body_json FROM requests WHERE rid=?", (rid,)).fetchone()
        if r is None:
            return None
        return {"fp": r[0], "state": r[1], "sub": r[2], "obo": r[3], "op": r[4], "status": r[5],
                "body": json.loads(r[6]) if r[6] else None}

    def prepare(self, rid: str, fp: str, pre: str, sub: str, obo: Any, op: str) -> None:
        if self.volatile:
            return  # MUTANT: nothing is journaled before the world commit
        with self._lock:
            # OR IGNORE: uniqueness of an in-flight request_id is the commit lock's job (Core._guard), not the table's
            self._con.execute("INSERT OR IGNORE INTO requests(rid,fp,state,pre,sub,obo,op) VALUES(?,?,?,?,?,?,?)",
                              (rid, fp, "PREPARED", pre, sub, obo, op))

    def finalize(self, rid: str, fp: str, sub: str, obo: Any, op: str, status: str, body: dict) -> None:
        with self._lock:
            if self.volatile:  # MUTANT: recorded only after the commit, only in memory
                self._mem[rid] = {"fp": fp, "state": "COMMITTED", "sub": sub, "obo": obo, "op": op, "status": status,
                                  "body": body}
                return
            self._con.execute("BEGIN IMMEDIATE")
            self._con.execute("UPDATE requests SET state='COMMITTED', status=?, body_json=?, pre=NULL WHERE rid=?",
                              (status, json.dumps(body, sort_keys=True), rid))
            self._con.execute("DELETE FROM approvals WHERE claimed_by=?", (rid,))  # one approval authorises one commit
            self._con.execute("COMMIT")

    def abort(self, rid: str) -> None:
        with self._lock:
            if self.volatile:
                return
            self._con.execute("BEGIN IMMEDIATE")
            self._con.execute("DELETE FROM requests WHERE rid=? AND state='PREPARED'", (rid,))
            self._con.execute("UPDATE approvals SET claimed_by=NULL WHERE claimed_by=?", (rid,))
            self._con.execute("COMMIT")

    def recover(self, digest_now: str) -> list[tuple[str, str]]:
        """Resolve PREPARED rows left by a crash. Returns [(rid, 'committed'|'aborted')]."""
        out = []
        with self._lock:
            rows = self._con.execute("SELECT rid,pre FROM requests WHERE state='PREPARED'").fetchall()
            for rid, pre in rows:
                if pre != digest_now:  # the world moved after prepare: the commit happened, only the ack was lost
                    self._con.execute("UPDATE requests SET state='COMMITTED', status='OK', body_json=?, pre=NULL WHERE rid=?",
                                      (json.dumps({"recovered": True}), rid))
                    self._con.execute("DELETE FROM approvals WHERE claimed_by=?", (rid,))
                    out.append((rid, "committed"))
                else:
                    self.abort(rid)
                    out.append((rid, "aborted"))
        return out

    # ---- approvals (single use, durable) ------------------------------------------------------
    def add_approval(self, fp: str, approver: str, decision_id: str | None = None) -> None:
        with self._lock:
            if self.volatile:
                self._mem_appr.append({"fp": fp, "approver": approver})
                return
            self._con.execute("INSERT INTO approvals(fp,approver) VALUES(?,?)", (fp, approver))

    def claim_approval(self, fp: str, rid: str, verify=None) -> str | None:
        """Claim the oldest unused approval for this exact request fingerprint; returns the approver pid."""
        with self._lock:
            if self.volatile:
                for a in self._mem_appr:
                    if a["fp"] == fp:
                        self._mem_appr.remove(a)
                        return a["approver"]
                return None
            r = self._con.execute("SELECT id,approver FROM approvals WHERE fp=? AND claimed_by IS NULL ORDER BY id LIMIT 1",
                                  (fp,)).fetchone()
            if r is None:
                return None
            self._con.execute("UPDATE approvals SET claimed_by=? WHERE id=?", (rid, r[0]))
            return r[1]

    def consume(self, rid: str) -> None:
        with self._lock:
            if not self.volatile:
                self._con.execute("DELETE FROM approvals WHERE claimed_by=?", (rid,))

    def release_approval(self, rid: str) -> None:
        with self._lock:
            if not self.volatile:
                self._con.execute("UPDATE approvals SET claimed_by=NULL WHERE claimed_by=?", (rid,))

    def commit_row(self, rid: str, fp: str, sub: str, obo: Any, op: str, status: str, body: dict) -> None:
        """Gate 2: a request whose effect is the authority change itself (delegate/revoke): COMMITTED row, no PREPARED phase."""
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO requests(rid,fp,state,pre,sub,obo,op,status,body_json) "
                              "VALUES(?,?,?,?,?,?,?,?,?)", (rid, fp, "COMMITTED", None, sub, obo, op, status,
                                                            json.dumps(body, sort_keys=True)))

    def drop(self, rid: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM requests WHERE rid=?", (rid,))

    def claimed_record(self, rid: str) -> dict | None:
        return None

    # ---- authority in force ---------------------------------------------------------------------
    def put_meta(self, k: str, v: Any) -> None:
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, json.dumps(v, sort_keys=True)))

    def get_meta(self, k: str) -> Any:
        with self._lock:
            r = self._con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return None if r is None else json.loads(r[0])
