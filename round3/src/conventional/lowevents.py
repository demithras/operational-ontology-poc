"""Subscriptions (PROT-H26 3.5): events are produced from the SAME LowView the read channels use. poll() replays the
committed world_log transactions after the subscription cursor on a private copy of the world, builds the observer's low
view before and after each transaction, and emits an event only where that projection changed (frozen event form)."""
from __future__ import annotations

import json
import sqlite3

from r3_shared.variant import CallResult

from .worldview import WorldView

BAD_SUB = CallResult("INVALID", {"reason": "unknown_subscription"})


def _wv(objs: dict, links: dict, now: int) -> WorldView:
    return WorldView(objs, {lt: sorted(v) for lt, v in links.items()}, now)


class LowEvents:
    def _ev_init(self) -> None:
        self._subs: dict[str, dict] = {}
        self._subn: dict[str, int] = {}

    def subscribe(self, token: str, spec: dict) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self.authenticate(token)
            if sub is None:
                return CallResult("DENIED", {"reason": "invalid_token"})
            names = {t["name"] for t in self._spec["resource_types"]}
            ts = spec.get("types") if isinstance(spec, dict) and set(spec) == {"types"} else None
            if not isinstance(ts, list) or not all(isinstance(t, str) and t in names for t in ts):
                return CallResult("INVALID", {"reason": "schema"})
            h = self._factory("conventional-service")
            try:
                w = WorldView.load(h, self._spec, self._clock.now())
                head = h._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0]
            finally:
                h.close()
            n = self._subn[sub] = self._subn.get(sub, 0) + 1
            sid = f"sub-{sub}-{n}"  # derived from the principal and a per-principal counter, never uuid/time (PROT-H26 s5)
            objs = {f"{t}:{k}": dict(p) for t in names for k, p in w.items(t)}
            links = {lt: set(w.all_links(lt)) for lt in {x["name"] for x in self._spec["link_types"]}}
            self._subs[sid] = {"who": sub, "types": set(ts), "cursor": head, "objs": objs, "links": links}
            return CallResult("OK", {"sub": sid})

    def poll(self, token: str, sub: str) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            who = self.authenticate(token)
            st = self._subs.get(sub) if isinstance(sub, str) else None
            if who is None or st is None or st["who"] != who:
                return BAD_SUB  # a foreign subscription is indistinguishable from an absent one
            h = self._factory("conventional-service")
            try:
                rows = h._con.execute("SELECT seq,tx,tick,kind,ref,data_json FROM world_log WHERE seq>? ORDER BY seq",
                                      (st["cursor"],)).fetchall()
            except sqlite3.Error:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})
            finally:
                h.close()
            events, txs = [], {}
            for r in rows:
                txs.setdefault(r[1], []).append(r)
            for rs in txs.values():
                events += self._tx_events(st, rs)
                st["cursor"] = rs[-1][0]
            return CallResult("OK", {"events": events})

    def _tx_events(self, st: dict, rs: list) -> list[dict]:
        seq, tick = rs[0][0], rs[0][2]
        touch = [r for r in rs if r[3] in ("create", "update", "delete", "link", "unlink")]
        if not touch:
            return []
        unfiltered = self.mutant("subscription_unfiltered")
        before = None if unfiltered else self._vb.build(self._policy, st["who"], _wv(st["objs"], st["links"], tick), tick)
        raw: list[dict] = []
        for _, _, _, kind, ref, dj in touch:
            d = json.loads(dj)
            if kind in ("create", "update", "delete"):
                if kind == "delete":
                    st["objs"].pop(ref, None)
                else:
                    st["objs"][ref] = dict(d["props"])
                raw.append({"kind": kind, "ref": ref, "props": dict(d.get("patch", d["props"])) if kind != "delete" else {}})
            else:
                key = (d["src"], d["dst"])
                (st["links"][d["link_type"]].add if kind == "link" else st["links"][d["link_type"]].discard)(key)
                raw.append({"kind": kind, "link": [d["link_type"], d["src"], d["dst"]], "props": {}})
        if unfiltered:  # BUG: every committed change is delivered with its true values
            return [{"seq": seq, "tick": tick, **e} for e in raw if self._ev_type(st, e)]
        after = self._vb.build(self._policy, st["who"], _wv(st["objs"], st["links"], tick), tick)
        out: list[dict] = []
        for ref in sorted(before.vis | after.vis):
            if ref.split(":", 1)[0] not in st["types"]:
                continue
            if ref in after.vis and ref not in before.vis:
                out.append({"kind": "create", "ref": ref, "props": dict(after.props[ref])})
            elif ref in before.vis and ref not in after.vis:
                out.append({"kind": "delete", "ref": ref, "props": {}})
            elif before.props[ref] != after.props[ref]:
                out.append({"kind": "update", "ref": ref, "props": {f: v for f, v in after.props[ref].items()
                                                                     if before.props[ref].get(f) != v}})
        for lt, a, b in sorted(after.links - before.links):
            out.append({"kind": "link", "link": [lt, a, b], "props": {}})
        for lt, a, b in sorted(before.links - after.links):
            out.append({"kind": "unlink", "link": [lt, a, b], "props": {}})
        return [{"seq": seq, "tick": tick, **e} for e in out if self._ev_type(st, e)]

    @staticmethod
    def _ev_type(st: dict, e: dict) -> bool:
        refs = [e["ref"]] if "ref" in e else e["link"][1:]
        return any(r.split(":", 1)[0] in st["types"] for r in refs)
