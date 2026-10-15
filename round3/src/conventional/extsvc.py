"""Service-side glue for the Gate 4 seam (P1f-1): post-commit dispatch, dispatch_pending / reconcile / outcome.

Decision-plane code never reads anything from here: the governed status of a request is final before `_post_commit` runs, and
an adapter reply can only add the `outcomes` list to an OK body (R28-1, R28-2).
"""
from __future__ import annotations

from r3_shared.variant import CallResult

from . import extrecon

WRITER = "conventional-service"


class ExternalOps:
    """Mixed into Service; expects self._ext (Outbox | None), self._factory, self._lock, self._clock, self.crashed."""

    def _envelope_text(self, rid: str) -> str:
        """H27 envelope of the decision, byte-exact (UTF-8 text of the canonical bytes); "" when none exists."""
        if getattr(self, "history", None) is None or getattr(self, "anchor", None) is None:
            return ""
        try:
            entry = self.anchor.lookup(self.stream, rid)
            raw = self.history.get(f"env/{entry['seq']:010d}") if entry is not None else None
            return raw.decode() if raw else ""
        except Exception:  # noqa: BLE001 - no envelope available: the field is "" (P1f-7)
            return ""

    def _post_commit(self, dc, res: CallResult) -> CallResult:
        """After the governed decision is final: dispatch fresh intents inline and attach the PENDING+ outcome list."""
        if self._ext is None or res.status != "OK" or self.crashed:
            return res
        rid = dc.extra.get("ext_rid") or res.body.get("request_id")
        if not isinstance(rid, str):
            return res
        h = self._factory(WRITER)
        try:
            if dc.extra.get("ext_rid"):  # fresh commit; a replay never dispatches again (R28-8)
                try:
                    self._ext.dispatch(h, self._envelope_text, self._clock.now(), rid)
                except Exception:  # noqa: BLE001 - an adapter/dispatch fault never changes the decision status (R28-2)
                    pass
            outs = self._ext.outcomes(h, rid)
        finally:
            h.close()
        return CallResult("OK", {**res.body, "outcomes": outs}) if outs else res

    # -- Gate 4 Deployment methods ---------------------------------------------------------------------------------------
    def dispatch_pending(self) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._ext is None:
                return CallResult("OK", {"submitted": 0})
            if getattr(self, "_g5", None) is not None:
                self._g5_anchor()   # recovery: finish the anchoring of committed-but-unanchored decisions first (no-op if ANCHOR is down)
            h = self._factory(WRITER)
            try:
                return CallResult("OK", {"submitted": self._ext.dispatch(h, self._envelope_text, self._clock.now())})
            finally:
                h.close()

    def reconcile(self, request_id, watermark) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._ext is None or not isinstance(request_id, str):
                return CallResult("INVALID", {"reason": "unknown_request"})
            if not isinstance(watermark, int) or isinstance(watermark, bool) or watermark < 0:
                return CallResult("INVALID", {"reason": "bad_watermark"})
            h = self._factory(WRITER)
            try:
                intents = self._ext.intents(h, request_id)
                if not intents:
                    return CallResult("INVALID", {"reason": "unknown_request"})
                extrecon.reconcile(h, intents, self._ext.b.observer, watermark, self._ext.mut, self._ext.guard)
                return CallResult("OK", {"outcomes": self._ext.outcomes(h, request_id)})
            finally:
                h.close()

    def outcome(self, request_id) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            h = self._factory(WRITER)
            try:
                outs = self._ext.outcomes(h, request_id) if self._ext is not None and isinstance(request_id, str) else []
                return CallResult("OK", {"outcomes": outs}) if outs else CallResult("INVALID", {"reason": "unknown_request"})
            finally:
                h.close()
