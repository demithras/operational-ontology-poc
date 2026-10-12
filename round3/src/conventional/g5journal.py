"""Durable anchor journal (PROT-H29 R29-4, R29-5): one row per committed governed decision, written in the SAME world transaction
as the effects, holding everything needed to rebuild and (re)anchor the decision envelope after a crash or an anchor outage.
A committed decision whose anchor step did not complete has anchored=0; redelivery of its request_id (or the first governed call
after a resume) completes it idempotently, so the original decision is returned only after its root is anchored."""
from __future__ import annotations

import json

DDL = """
CREATE TABLE IF NOT EXISTS conv_journal(
  n INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE, prep_json TEXT NOT NULL, anchored INTEGER NOT NULL DEFAULT 0);
"""


def init(h) -> None:
    h._con.executescript(DDL)


def prep_record(dc, status: str, body: dict, authority_doc: dict) -> dict:
    return {"kind": dc.kind, "subject": dc.subject, "obo": dc.obo, "operation": dc.operation, "args": dc.args,
            "path": list(dc.path), "tick": dc.tick, "world_seq": dc.world_seq, "tx_id": dc.tx_id,
            "evidence": [e.decode() for e in (dc.evidence or [])], "authority_doc": authority_doc,
            "status": status, "body": body}


def put(h, rid: str, prep: dict) -> None:
    h._con.execute("INSERT OR IGNORE INTO conv_journal(request_id, prep_json) VALUES(?,?)",
                   (rid, json.dumps(prep, sort_keys=True)))


def get_open(h, rid: str):
    r = h._con.execute("SELECT prep_json FROM conv_journal WHERE request_id=? AND anchored=0", (rid,)).fetchone()
    return None if r is None else json.loads(r[0])


def open_ids(h) -> list[str]:
    return [r[0] for r in h._con.execute("SELECT request_id FROM conv_journal WHERE anchored=0 ORDER BY n")]


def mark_done(h, rid: str) -> None:
    h._con.execute("UPDATE conv_journal SET anchored=1 WHERE request_id=?", (rid,))
