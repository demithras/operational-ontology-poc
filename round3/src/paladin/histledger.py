"""The Ledger interface (paladin.ledger) over an r3_shared HistoryStore: every durable record of the request ledger,
single-use approvals and the authority in force lives in the (attackable) HistoryStore when `history` is given (PROT-H27 s4,
PROTOCOL-P1d P1d-4). Same prepare / commit / finalize protocol as the SQLite ledger; writers are serialised by the Core lock.

Keys: led/req/<request_id>, led/appr/<n>, led/meta/<name>. Records are canonical JSON bytes.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from r3_shared.evidence import canonical_bytes

REQ, APPR, META = "led/req/", "led/appr/", "led/meta/"


class HistLedger:
    volatile = False

    def __init__(self, history):
        self.h = history
        self._lock = threading.RLock()

    def _load(self, key: str) -> Any:
        raw = self.h.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return {"_corrupt": True}

    def _store(self, key: str, rec: Any) -> None:
        self.h.put(key, canonical_bytes(rec))

    # ---- requests -----------------------------------------------------------------------------
    def get(self, rid: str) -> dict | None:
        with self._lock:
            r = self._load(REQ + rid)
        if r is None:
            return None
        if "fp" not in r or "state" not in r:  # a corrupted record never reads as a result
            return {"fp": None, "state": "CORRUPT", "sub": None, "obo": None, "op": None, "status": None, "body": None}
        return {k: r.get(k) for k in ("fp", "state", "sub", "obo", "op", "status", "body")}

    def prepare(self, rid, fp, pre, sub, obo, op) -> None:
        with self._lock:
            if self.h.get(REQ + rid) is None:
                self._store(REQ + rid, {"fp": fp, "state": "PREPARED", "pre": pre, "sub": sub, "obo": obo, "op": op})

    def commit_row(self, rid, fp, sub, obo, op, status, body) -> None:
        with self._lock:
            self._store(REQ + rid, {"fp": fp, "state": "COMMITTED", "sub": sub, "obo": obo, "op": op, "status": status,
                                    "body": body})

    def finalize(self, rid, fp, sub, obo, op, status, body) -> None:
        with self._lock:
            self.commit_row(rid, fp, sub, obo, op, status, body)
            self._drop_claims(rid, consume=True)

    def drop(self, rid: str) -> None:
        with self._lock:
            self.h.delete(REQ + rid)

    def abort(self, rid: str) -> None:
        with self._lock:
            r = self._load(REQ + rid)
            if r is not None and r.get("state") == "PREPARED":
                self.h.delete(REQ + rid)
            self._drop_claims(rid, consume=False)

    def recover(self, digest_now: str) -> list[tuple[str, str]]:
        out = []
        with self._lock:
            for k in self.h.keys(REQ):
                r = self._load(k)
                if not r or r.get("state") != "PREPARED":
                    continue
                rid = k[len(REQ):]
                if r.get("pre") != digest_now:
                    self._store(k, {**r, "state": "COMMITTED", "status": "OK", "body": {"recovered": True}, "pre": None})
                    self._drop_claims(rid, consume=True)
                    out.append((rid, "committed"))
                else:
                    self.abort(rid)
                    out.append((rid, "aborted"))
        return out

    # ---- approvals ----------------------------------------------------------------------------
    def _appr_keys(self) -> list[str]:
        return self.h.keys(APPR)

    def add_approval(self, fp: str, approver: str, decision_id: str | None = None) -> None:
        with self._lock:
            ks = self._appr_keys()
            n = (max(int(k[len(APPR):]) for k in ks if k[len(APPR):].isdigit()) + 1) if ks else 1
            self._store(f"{APPR}{n:08d}", {"fp": fp, "approver": approver, "claimed_by": None, "decision_id": decision_id})

    def claim_approval(self, fp: str, rid: str, verify: Callable[[dict], bool] | None = None) -> str | None:
        with self._lock:
            for k in self._appr_keys():
                r = self._load(k)
                if not r or r.get("_corrupt") or r.get("fp") != fp or r.get("claimed_by") is not None:
                    continue
                if verify is not None and not verify(r):
                    continue
                self._store(k, {**r, "claimed_by": rid})
                return r["approver"]
        return None

    def _drop_claims(self, rid: str, consume: bool) -> None:
        for k in self._appr_keys():
            r = self._load(k)
            if r and r.get("claimed_by") == rid:
                if consume:
                    self.h.delete(k)
                else:
                    self._store(k, {**r, "claimed_by": None})

    def consume(self, rid: str) -> None:
        with self._lock:
            self._drop_claims(rid, True)

    def release_approval(self, rid: str) -> None:
        with self._lock:
            self._drop_claims(rid, False)

    def claimed_record(self, rid: str) -> dict | None:
        with self._lock:
            for k in self._appr_keys():
                r = self._load(k)
                if r and r.get("claimed_by") == rid:
                    return r
        return None

    # ---- meta ---------------------------------------------------------------------------------
    def put_meta(self, k: str, v: Any) -> None:
        with self._lock:
            self._store(META + k, v)

    def get_meta(self, k: str) -> Any:
        with self._lock:
            return self._load(META + k)
