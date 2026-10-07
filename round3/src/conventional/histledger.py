"""Durable records in the HistoryStore (PROT-H27 / PROTOCOL-P1d P1d-4: used when `history` is given).

Event-sourced split: the WORLD LOG (never attacker-controlled in H27) is the source of truth for *whether* something
committed (`commit`, `approval`, `approval_used`, `authority` marks written in the same transaction as the effect); the
HistoryStore holds the records themselves (idempotency result, approval, authority-version blobs, artifacts, envelopes).
A record that is missing or inconsistent with the world log yields LedgerUnresolved -> a non-OK result with zero effects.
"""
from __future__ import annotations

import hashlib
import json

from r3_shared.authgraph import authority_document
from r3_shared.evidence import canonical_bytes, sha256_of

from .authdoc import upgraded  # noqa: F401  (re-export for callers)

HISTORY_LAYOUT = {"envelope": "env/", "receipt": "receipt/", "artifact": "art/", "approval": "approval/",
                  "idempotency": "ledger/", "meta": "meta/", "evidence_index": "evref/", "policy_side": "side/"}


class LedgerUnresolved(Exception):
    """A durable record needed to decide is missing/inconsistent (never guessed): refuse, zero effects."""


def rid_key(rid: str) -> str:
    return "ledger/" + hashlib.sha256(rid.encode()).hexdigest()


def commit_mark(h, rid: str):
    """(seq, tx, tick) of the `commit` mark for request_id `rid`, or None. The world log is authoritative."""
    return h._con.execute("SELECT seq, tx, tick FROM world_log WHERE kind='mark' AND ref='commit' "
                          "AND json_extract(data_json,'$.request_id')=? ORDER BY seq LIMIT 1", (rid,)).fetchone()


def tx_effect_rows(h, tx: int) -> int:
    return h._con.execute("SELECT COUNT(*) FROM world_log WHERE tx=? AND kind!='mark'", (tx,)).fetchone()[0]


class HistLedger:
    uses_history = True

    def __init__(self, history):
        self.history = history

    def init(self, h) -> None:
        pass

    # -- idempotency ----------------------------------------------------------------------------
    def idem_get(self, h, rid: str):
        m = commit_mark(h, rid)
        if m is None:
            return None  # never committed (an orphan 'prepared' record, if any, is overwritten by the next attempt)
        raw = self.history.get(rid_key(rid))
        try:
            rec = json.loads(raw) if raw is not None else None
            if rec is None or rec["status"] != "OK" or not isinstance(rec["body"], dict) \
                    or not isinstance(rec["used"], dict):
                raise ValueError
            return rec["fp"], {"status": rec["status"], "body": rec["body"], "used": rec["used"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerUnresolved("idempotency record missing or inconsistent with the world log") from exc

    def idem_put(self, h, rid: str, fp: str, rec: dict) -> None:
        self.history.put(rid_key(rid), canonical_bytes({"fp": fp, **rec}))

    # -- approvals: world-log marks decide; the HistoryStore copy must agree -----------------------
    def approval_add(self, h, fp: str, approver: str, tx) -> int:
        seq = tx.mark("approval", {"fp": fp, "approver": approver})
        self.history.put(f"approval/{seq:010d}", canonical_bytes({"fp": fp, "approver": approver, "seq": seq}))
        return seq

    def approvals_open(self, h, fp: str):
        used = {json.loads(r[0])["approval"] for r in h._con.execute(
            "SELECT data_json FROM world_log WHERE kind='mark' AND ref='approval_used'")}
        out = []
        for seq, d in h._con.execute("SELECT seq, data_json FROM world_log WHERE kind='mark' AND ref='approval' ORDER BY seq"):
            m = json.loads(d)
            if m["fp"] != fp or seq in used:
                continue
            raw = self.history.get(f"approval/{seq:010d}")
            if raw is None or json.loads(raw) != {"fp": fp, "approver": m["approver"], "seq": seq}:
                raise LedgerUnresolved("approval record missing or altered")
            out.append((seq, m["approver"]))
        return out

    def approval_consume(self, h, aid: int, tx) -> None:
        tx.mark("approval_used", {"approval": aid})  # same transaction as the effect: a rollback un-consumes it

    def approval_restore(self, h, aid) -> None:
        pass  # nothing to undo: the consume mark rolled back with the world transaction

    # -- authority versions -----------------------------------------------------------------------
    def authority_put(self, h, version: int, doc: dict) -> None:
        raw = canonical_bytes(authority_document(doc))
        self.history.put(f"art/{hashlib.sha256(raw).hexdigest()}", raw)
        if version == 1:
            self.history.put("meta/initial_authority", hashlib.sha256(raw).hexdigest().encode())

    def authority_get(self, h):
        marks = [json.loads(r[0]) for r in h._con.execute(
            "SELECT data_json FROM world_log WHERE kind='mark' AND ref='authority' ORDER BY seq")]
        digest = marks[-1]["version"] if marks else (self.history.get("meta/initial_authority") or b"").decode()
        raw = self.history.get(f"art/{digest}") if digest else None
        if raw is None:
            if marks or digest:  # E-7: a lineage that names a version whose blob is gone is damaged, never "fresh"
                raise LedgerUnresolved("authority version blob is missing")
            return None
        if hashlib.sha256(raw).hexdigest() != digest:
            raise LedgerUnresolved("authority version blob does not hash to its digest")
        return 1 + len(marks), json.loads(raw)


__all__ = ["HistLedger", "LedgerUnresolved", "HISTORY_LAYOUT", "sha256_of"]
