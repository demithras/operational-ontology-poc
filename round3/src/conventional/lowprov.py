"""Provenance low channels (PROT-H26 s4; P1e-5): prov_decision / prov_object / authority_used_as. The decision envelopes
and the idempotency ledger hold the TRUE values; every view is projected through the observer's LowView and capability-edge
visibility, with an EXPLICIT marker wherever a value is withheld. Views never claim completeness ("partial": true)."""
from __future__ import annotations

import json
import sqlite3

from r3_shared.disclosure import marker
from r3_shared.variant import CallResult

from . import authdoc
from .histledger import LedgerUnresolved, commit_mark

UNKNOWN = CallResult("INVALID", {"reason": "unknown_decision"})


class LowProv:
    def _index_rows(self) -> list[dict]:
        if self.history is None:
            return []
        return [json.loads(self.history.get(k)) for k in self.history.keys("decidx/")]

    def _envelope(self, seq: int) -> dict | None:
        raw = self.history.get(f"env/{seq:010d}")
        return None if raw is None else json.loads(raw)["decision"]

    def _own(self, sub: str, d: dict) -> bool:
        return sub in (d["subject"], d["on_behalf_of"])

    def _decision_low(self, sub, lv, doc, idx: dict, d: dict) -> tuple[bool, bool]:
        """-> (low, actors_level). OWN decisions are low with actors; else every resource input must be existence-visible
        with a covering provenance level of at least `scalars` (edge decisions: the edge must be visible)."""
        if self._own(sub, d):
            return True, True
        if idx["edge"] is not None:
            return authdoc.edge_visible(doc, idx["edge"], sub), False
        if not idx["refs"] or not all(lv.has(r) and lv.prov.get(r) in ("scalars", "actors") for r in idx["refs"]):
            return False, False
        return True, all(lv.prov[r] == "actors" for r in idx["refs"])

    def _path_view(self, sub, doc, path: list[str]) -> list:
        mut = self.mutant("provenance_edge_retained")
        out = []
        for e in path:
            if mut or authdoc.edge_visible(doc, e, sub):
                out.append(e)
            else:
                out.append("system" if self.mutant("redaction_fabrication") else marker("edge"))
        return out

    def _actor(self, sub, value, ok: bool):
        if ok or self.mutant("provenance_edge_retained"):
            return value
        return "system" if self.mutant("redaction_fabrication") else marker("actor")

    def prov_decision(self, token: str, decision_id: str) -> CallResult:
        def go(sub, lv, world, h):
            if sub is None or not isinstance(decision_id, str):
                return UNKNOWN
            doc = self._policy.doc
            for idx in self._index_rows():
                if idx["id"] != decision_id:
                    continue
                d = self._envelope(idx["seq"])
                low, actors = self._decision_low(sub, lv, doc, idx, d) if d else (False, False)
                if not low:
                    return UNKNOWN
                own = self._own(sub, d)
                args_ok = own or (bool(idx["refs"]) and d["operation"] is not None and self._args_low(idx, lv))
                view = dict(d)
                view["subject"] = self._actor(sub, d["subject"], actors)
                view["on_behalf_of"] = self._actor(sub, d["on_behalf_of"], actors)
                view["args_digest"] = d["args_digest"] if args_ok else marker("args")
                view["effect_digest"] = d["effect_digest"] if own else marker("digest")
                view["authority_path"] = self._path_view(sub, doc, d["authority_path"])
                return CallResult("OK", {"partial": True, "decision": view})
            return UNKNOWN
        return self._low(token, go)

    def _args_low(self, idx: dict, lv) -> bool:
        """args_digest covers the request args: low iff every byte of them is low. Plain (non-resource) input values are
        the requester's own and not low to others, so only args consisting solely of visible resource keys qualify."""
        return idx.get("pure_refs", False) and all(lv.has(r) for r in idx["refs"])

    def prov_object(self, token: str, ref: str) -> CallResult:
        def go(sub, lv, world, h):
            if sub is None or not isinstance(ref, str) or not lv.has(ref):
                return CallResult("OK", {"partial": True, "decisions": []})  # hidden == absent
            doc, out = self._policy.doc, []
            for idx in self._index_rows():
                if ref in idx["refs"]:
                    d = self._envelope(idx["seq"])
                    if d and self._decision_low(sub, lv, doc, idx, d)[0]:
                        out.append(idx["id"])
            return CallResult("OK", {"partial": True, "decisions": out})
        return self._low(token, go)

    def authority_used_as(self, token: str, request_id: str) -> CallResult:
        def go(sub, lv, world, h):
            if sub is None or not isinstance(request_id, str):
                return UNKNOWN
            try:
                m = commit_mark(h, request_id)
                prior = self._store.idem_get(h, request_id) if m is not None else None
            except (sqlite3.Error, LedgerUnresolved):
                return UNKNOWN
            if prior is None or prior[1]["used"].get("subject") != sub:
                return UNKNOWN  # only OWN requests; foreign/unknown are indistinguishable
            u = prior[1]["used"]
            av = u["authority_version"] if self.mutant("provenance_edge_retained") else marker("digest")
            return CallResult("OK", {"partial": True, "on_behalf_of": u["on_behalf_of"],
                                     "path": self._path_view(sub, self._policy.doc, list(u["path"])),
                                     "authority_version": av, "world_seq": m[0], "tick": m[2]})
        return self._low(token, go)
