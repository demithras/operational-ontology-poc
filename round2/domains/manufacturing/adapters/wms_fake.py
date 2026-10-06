"""In-process fake WMS honouring the adapter allowlist of protocol/ENGINE_PREREG.json (H20).

Allowed: translate an approved effect into a call on this system, return the raw response, emit observations.
Forbidden (and absent here): authority, policy, preconditions, idempotency *decisions of the Engine*, provenance,
lifecycle state. The WMS' own behaviour that real WMS would also have is modelled: it keeps stock, it keys a transfer
record by the action execution id (a repeated call returns the same record, never moves stock twice), and its CDC
stream emits one WmsTransferRecordObserved per record.

Fault modes (set ``wms.mode``): ok | reject (FAILED record, zero effect) | partial (half committed) |
wrong_quantity (+1 committed) | timeout (raises before touching stock) | commit_no_response (stock moves, the
record is in CDC, the response is lost: raises). ``wms.cdc_visible = False`` hides the CDC stream (lag).
"""
from __future__ import annotations

from typing import Any, Iterable


class WmsUnavailable(TimeoutError):
    """The WMS did not answer (no response was received by the caller)."""


class WmsFake:
    MODES = ("ok", "reject", "partial", "wrong_quantity", "timeout", "commit_no_response")

    def __init__(self, stock: dict | None = None):
        self.stock: dict[tuple, int] = dict(stock or {})  # (part, warehouse) -> available units
        self.records: dict[str, dict] = {}  # execution id -> transfer record
        self.calls: list[dict] = []  # every apply() call, for tests
        self.mode = "ok"
        self.cdc_visible = True

    @classmethod
    def from_seed(cls, seed: dict) -> "WmsFake":
        """Initial stock = available (onHand - reserved) of each seeded InventoryLot."""
        links = {(o["type"], tuple(o["src"])[1]): tuple(o["dst"])[1] for o in seed["ops"] if o["op"] == "link"}
        stock = {}
        for o in seed["ops"]:
            if o["op"] == "create" and o["type"] == "InventoryLot":
                k = o["key"]
                stock[(links[("PartReferencing_part", k)], links[("InventoryLot_warehouse", k)])] = \
                    o["props"]["onHand"] - o["props"]["reserved"]
        return cls(stock)

    # -- Adapter interface ------------------------------------------------------------------
    def apply(self, effect: Any, payload: Any) -> dict:
        xid = effect["execution"]
        self.calls.append({"execution": xid, "payload": dict(payload), "mode": self.mode})
        if xid in self.records:  # WMS-side idempotency on the execution id
            return dict(self.records[xid])
        if self.mode == "timeout":
            raise WmsUnavailable("WMS timed out before accepting the command")
        src, dst, part, qty = payload["source"], payload["destination"], payload["part"], payload["quantity"]
        if self.mode == "reject" or self.stock.get((part, src), 0) < qty:
            rec = self._record(xid, qty, 0, "FAILED")
        else:
            actual = {"partial": qty // 2, "wrong_quantity": qty + 1}.get(self.mode, qty)
            actual = min(actual, self.stock.get((part, src), 0))
            self.stock[(part, src)] -= actual
            self.stock[(part, dst)] = self.stock.get((part, dst), 0) + actual
            status = "COMMITTED" if actual == qty or self.mode == "wrong_quantity" else "PARTIAL"
            rec = self._record(xid, qty, actual, status)
        if self.mode == "commit_no_response":
            raise WmsUnavailable("WMS committed but the response was lost")
        return dict(rec)

    def observations(self) -> Iterable[dict]:
        if not self.cdc_visible:
            return []
        return [{"observation_type": "WmsTransferRecordObserved", "execution": xid,
                 "data": {"transferStatus": r["transferStatus"], "requestedQuantity": r["requestedQuantity"],
                          "actualQuantity": r["actualQuantity"]}} for xid, r in sorted(self.records.items())]

    # -- fake internals ---------------------------------------------------------------------
    def _record(self, xid: str, requested: int, actual: int, status: str) -> dict:
        self.records[xid] = {"actionExecutionId": xid, "requestedQuantity": requested, "actualQuantity": actual,
                             "transferStatus": status}
        return self.records[xid]
