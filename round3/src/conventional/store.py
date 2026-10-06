"""Durable auxiliary tables (idempotency + approvals) kept in the same SQLite file as the world, so they commit or roll
back atomically with the effects. They are NOT canonical objects: WorldReader snapshots do not see them.
Uses the handle's connection (`_con`): r3_shared offers no auxiliary-table API (reported in BUILD_NOTES)."""
from __future__ import annotations

import hashlib
import json

DDL = """
CREATE TABLE IF NOT EXISTS conv_idempotency(request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conv_approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL, approver TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
"""


def fingerprint(subject: str, on_behalf_of: str | None, operation: str, inputs: dict) -> str:
    doc = {"subject": subject, "on_behalf_of": on_behalf_of, "operation": operation, "inputs": inputs}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def init(handle) -> None:
    handle._con.executescript(DDL)


def idem_get(handle, request_id: str):
    r = handle._con.execute("SELECT fingerprint, result_json FROM conv_idempotency WHERE request_id=?",
                            (request_id,)).fetchone()
    return None if r is None else (r[0], json.loads(r[1]))


def idem_put(handle, request_id: str, fp: str, result: dict) -> None:
    handle._con.execute("INSERT INTO conv_idempotency VALUES(?,?,?)", (request_id, fp, json.dumps(result, sort_keys=True)))


def approval_add(handle, fp: str, approver: str) -> None:
    handle._con.execute("INSERT INTO conv_approvals(fingerprint, approver) VALUES(?,?)", (fp, approver))


def approvals_open(handle, fp: str) -> list[tuple[int, str]]:
    return [(r[0], r[1]) for r in handle._con.execute(
        "SELECT id, approver FROM conv_approvals WHERE fingerprint=? AND consumed=0 ORDER BY id", (fp,))]


def approval_consume(handle, approval_id: int) -> None:
    handle._con.execute("UPDATE conv_approvals SET consumed=1 WHERE id=?", (approval_id,))
