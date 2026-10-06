"""In-process fake ERP (expedite purchase order) and MES (reschedule work order) with the same adapter surface."""
from __future__ import annotations

from typing import Any, Iterable


class _Fake:
    obs_type = ""

    def __init__(self):
        self.calls: list[dict] = []
        self.mode = "ok"  # ok | timeout | commit_no_response
        self.cdc_visible = True
        self._obs: dict[str, dict] = {}

    def apply(self, effect: Any, payload: Any) -> dict:
        xid = effect["execution"]
        self.calls.append({"execution": xid, "payload": dict(payload)})
        if xid in self._obs:
            return {"status": 200, "execution": xid}
        if self.mode == "timeout":
            raise TimeoutError("no response")
        self._obs[xid] = self._observe(dict(payload))
        if self.mode == "commit_no_response":
            raise TimeoutError("committed, response lost")
        return {"status": 200, "execution": xid}

    def observations(self) -> Iterable[dict]:
        if not self.cdc_visible:
            return []
        return [{"observation_type": self.obs_type, "execution": x, "data": d} for x, d in sorted(self._obs.items())]

    def _observe(self, payload: dict) -> dict:
        raise NotImplementedError


class ErpFake(_Fake):
    obs_type = "PurchaseOrderObserved"

    def __init__(self, expedite_to: int = 24):
        super().__init__()
        self.expedite_to = expedite_to  # the new expectedAt the ERP reports after an expedite

    def _observe(self, payload: dict) -> dict:
        return {"expectedAt": self.expedite_to, "status": "EXPEDITED"}


class MesFake(_Fake):
    obs_type = "WorkOrderObserved"

    def _observe(self, payload: dict) -> dict:
        return {"plannedStart": payload["new_planned_start"]}
