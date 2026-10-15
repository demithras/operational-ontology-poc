"""Case journal + governance document blobs (PROT-H25 R25-7: durability). The world_log `governance` marks are the
authoritative ORDER and TIME of every constitutional action; this journal holds what a frozen mark cannot carry
(request ids, proposed args, stored execute results). Backend: auxiliary tables in the world DB (atomic with the mark)
or, when a HistoryStore is given, its keys (a missing/foreign record for a mark -> LedgerUnresolved, never guessed)."""
from __future__ import annotations

import json

from r3_shared.evidence import canonical_bytes

from .histledger import LedgerUnresolved

DDL = """
CREATE TABLE IF NOT EXISTS conv_gov(seq INTEGER PRIMARY KEY, rec_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conv_govdoc(digest TEXT PRIMARY KEY, doc_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conv_govmeta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class GovStore:
    def __init__(self, history=None):
        self.history = history

    def init(self, h) -> None:
        if self.history is None:
            h._con.executescript(DDL)

    # -- journal (keyed by the governance mark's seq) ------------------------------------------------------
    def put(self, h, seq: int, rec: dict) -> None:
        if self.history is not None:
            self.history.put(f"gov/{seq:010d}", canonical_bytes(rec))
        else:
            h._con.execute("INSERT OR REPLACE INTO conv_gov VALUES(?,?)", (seq, json.dumps(rec, sort_keys=True)))

    def get(self, h, seq: int) -> dict:
        if self.history is not None:
            raw = self.history.get(f"gov/{seq:010d}")
        else:
            r = h._con.execute("SELECT rec_json FROM conv_gov WHERE seq=?", (seq,)).fetchone()
            raw = None if r is None else r[0]
        if raw is None:
            raise LedgerUnresolved("governance journal record missing for a governance mark")
        return json.loads(raw)

    # -- governance documents by digest ---------------------------------------------------------------------
    def put_doc(self, h, digest: str, doc: dict) -> None:
        if self.history is not None:
            self.history.put(f"govdoc/{digest}", canonical_bytes(doc))
        else:
            h._con.execute("INSERT OR REPLACE INTO conv_govdoc VALUES(?,?)", (digest, json.dumps(doc, sort_keys=True)))

    def get_doc(self, h, digest: str) -> dict | None:
        if self.history is not None:
            raw = self.history.get(f"govdoc/{digest}")
        else:
            r = h._con.execute("SELECT doc_json FROM conv_govdoc WHERE digest=?", (digest,)).fetchone()
            raw = None if r is None else r[0]
        return None if raw is None else json.loads(raw)

    def set_initial(self, h, digest: str | None) -> None:
        v = digest or ""
        if self.history is not None:
            self.history.put("meta/gov_initial", v.encode())
        else:
            h._con.execute("INSERT OR REPLACE INTO conv_govmeta VALUES('initial',?)", (v,))

    def initial(self, h) -> str | None:
        if self.history is not None:
            raw = self.history.get("meta/gov_initial")
            v = None if raw is None else raw.decode()
        else:
            r = h._con.execute("SELECT v FROM conv_govmeta WHERE k='initial'").fetchone()
            v = None if r is None else r[0]
        return v or None
