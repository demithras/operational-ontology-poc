"""Durable outbox of external intents and outcome records (PROT-H28 R28-1, R28-8, P1f-1).

One record per committed request id, kept in the request ledger's meta store (SQLite file in state_dir, or the HistoryStore
under `led/meta/ext/...` when a history is given), written right after the world commit and BEFORE any adapter is called, so
restart() can resubmit the same per-effect cap. The record holds the intent (I + the cap), the attempt count and the adapter
reply STATUS only (never a reply body: nothing an adapter says is stored or read). Outcome records live next to the intent.
"""
from __future__ import annotations

from typing import Any

IDX = "ext/idx"


def _key(rid: str) -> str:
    return f"ext/r/{rid}"


class Outbox:
    def __init__(self, ledger):
        self.led = ledger

    def rids(self) -> list[str]:
        v = self.led.get_meta(IDX)
        return list(v) if isinstance(v, list) else []

    def get(self, rid: str) -> list[dict] | None:
        rec = self.led.get_meta(_key(rid))
        if not isinstance(rec, dict) or not isinstance(rec.get("effects"), list):
            return None                      # absent or corrupt: never read as an intent
        return rec["effects"]

    def put(self, rid: str, effects: list[dict]) -> None:
        new = self.get(rid) is None
        self.led.put_meta(_key(rid), {"effects": effects})
        if new:
            self.led.put_meta(IDX, [*self.rids(), rid])

    def update(self, rid: str, index: int, **fields: Any) -> dict:
        effs = self.get(rid) or []
        e = next(x for x in effs if x["index"] == index)
        e.update(fields)
        self.put(rid, effs)
        return e
