"""Gate 5 / H29 part of the Paladin deployment: dependency-aware decisions, explicit unavailability, recovery view.

Mixed into `paladin.deployment.PaladinDeployment`. Active only when `authority_source` was given to deploy() (`self._h29`); the
legacy path (H23-H28) never reaches any of it. The shape of a request's dependencies is the frozen graph read as DATA (depgraph).

Order of one governed call: dependencies probed (AUTH lease fetched or honoured, ANCHOR reachable) -> blocked? then the frozen
reply (UNAVAILABLE dependency_unavailable <node>, or INVALID for an input error decidable without AUTH) with ZERO effects ->
otherwise the unchanged Core pipeline; a commit the anchor never confirmed answers UNKNOWN in_doubt (Core.run).
"""
from __future__ import annotations

import json

from paladin.depgraph import DepGraph
from paladin.engine import canon as _canon
from paladin.leasing import LeaseGate
from paladin.surface import SurfaceFactory
from r3_shared.authgraph import authority_digest
from r3_shared.faultplane import CanonicalStateLost, DependencyUnavailable
from r3_shared.recovery import DEP_UNAVAILABLE, FORM, IN_DOUBT  # noqa: F401  (IN_DOUBT documents the Core reply)
from r3_shared.variant import CallResult


class ContinuityMixin:
    # ---- construction (called from PaladinDeployment.__init__/_build) --------------------------------------------------------
    def h29_setup(self, binding, resume, history, state_dir) -> None:
        self._h29, self._binding, self._resume = binding is not None, binding, resume
        self._seen: dict = {}
        if resume and ((history is None and (state_dir is None or not _exists(state_dir, "ledger.sqlite")))
                       or (history is not None and not history.keys("meta/") and not history.keys("led/"))):
            raise CanonicalStateLost("durable state absent or unreadable: refusing to start empty (PROT-H29 s9 B4)")

    def h29_build(self) -> None:
        c = self._c
        self._adopted = None
        if self._h29:
            self._deps = DepGraph(self._binding.graph, c.domain)
            self._gate = LeaseGate(self._binding, c.ledger, c.clock, c.mutants, self._resume)
            if "stale_cache_after_restart" in c.mutants and self._gate.held is not None:
                self._adopted = self._gate.held.digest   # MUTANT: the cached version is believed to be the installed one
                c.lease_version = self._adopted

    # ---- the dependency gate -----------------------------------------------------------------------------------------------
    def _adopt(self, lease) -> None:
        """Make the leased document the one the Core decides under (one `authority` mark, edges in force kept)."""
        c = self._c
        with c.lock:
            if self._adopted == lease.digest:
                return
            if self._adopted is None and authority_digest(c.auth) == lease.digest:
                self._adopted, c.lease_version = lease.digest, lease.digest
            else:
                before = c.lease_version
                c.lease_version = lease.digest   # the adoption mark carries the service version
                try:
                    c.replace_authority(lease.doc, keep_edges=True)
                except BaseException:
                    c.lease_version = before
                    raise
                self._adopted, self._surfaces = lease.digest, SurfaceFactory(c.booted.ir)
            self._auth_version = c.stamp()

    def _probe(self, nodes) -> str | None:
        """First node of `nodes` that blocks this decision now, else None. AUTH: lease fetched (or honoured inside its window)."""
        c, now = self._c, self._c.clock.now()
        if "global_halt_on_fault" in c.mutants:   # MUTANT: any fault anywhere halts everything
            nodes = tuple(dict.fromkeys((*nodes, "AUTH", "ANCHOR")))
            if c.ext is not None and c.ext.down:
                return sorted(c.ext.down)[0]
        for n in nodes:
            if n == "AUTH":
                try:
                    lease = self._gate.acquire(now)
                except DependencyUnavailable:
                    self._seen["AUTH"] = "DOWN"
                    return "AUTH"
                self._seen["AUTH"] = "UP" if self._gate.auth_up else "DOWN"
                self._adopt(lease)
            elif n == "ANCHOR" and c.prov is not None and "anchor_skipped_when_unavailable" not in c.mutants:
                try:
                    c.prov.a.head(c.prov.stream)
                    self._seen["ANCHOR"] = "UP"
                except DependencyUnavailable:
                    self._seen["ANCHOR"] = "DOWN"
                    return "ANCHOR"
        return None

    def _blocked(self, node: str, token, op, args, rid=None) -> CallResult:
        c = self._c
        if node == "AUTH" and "dependency_failure_as_denial" in c.mutants:   # MUTANT: a dependency failure dressed as a policy denial
            return CallResult("DENIED", {"gate": "authority", "reason": "not_authorized"})
        if op is not None and c.subject(token) is not None:   # an input error is decidable without AUTH (R29-7); only for an authenticated caller
            if not isinstance(args, dict) or c.schema_problem(op, args) is not None:
                return CallResult("INVALID", {"reason": "schema_invalid"})
        return CallResult("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": node})

    def guarded(self, token, op, args, fn, kind: str = "mutation"):
        """Run `fn` (the unchanged legacy call) behind the dependency gate. Legacy deployment (no authority_source): just `fn()`."""
        if not self._h29 or self._crashed:
            return fn()
        known = kind != "mutation" or self._deps.known(op)
        if known:
            node = self._probe(self._deps.mutation(op) if kind == "mutation" else self._deps.surface(kind))
            if node is not None:
                return self._blocked(node, token, op if kind == "mutation" and op in self._c.ops else None, args)
        res = fn()
        if isinstance(res, CallResult) and res.status == "UNAVAILABLE" and res.body.get("reason") == "anchor_unavailable":
            return CallResult("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": "ANCHOR"})   # zero effects: nothing committed
        return res

    # ---- G5 self-reports ----------------------------------------------------------------------------------------------------
    def dependency_status(self) -> dict:
        out = {}
        down = self._c.ext.down if self._c is not None and self._c.ext is not None else set()
        for n in (self._deps.nodes() if self._h29 else ()):
            out[n] = "DOWN" if n in down else self._seen.get(n, "UNKNOWN")
        return out

    def recovery_view(self) -> dict:
        """P1g-8: the canonical state this incarnation rebuilt, from the durable stores and the tick only (no dependency I/O, no
        mutation). committed = the world's own commit marks; intents = the outbox; authority = the version a lease held in THIS
        process verifies (null right after a restart: nothing is trusted before AUTH answers); approvals = unclaimed fingerprints."""
        c = self._c
        with c.lock:
            rows = c._svc._con.execute("SELECT seq,data_json FROM world_log WHERE kind='mark' AND ref='commit' ORDER BY seq").fetchall()
            committed = []
            for seq, raw in rows:
                m = json.loads(raw)
                committed.append({"request_id": m.get("request_id"), "world_seq": seq, "authority_version": m.get("authority_version")})
            intents = []
            if c.ext is not None:
                for rid in c.ext.box.rids():
                    for e in c.ext.box.get(rid) or []:
                        o = e["outcome"]
                        intents.append({"request_id": rid, "effect_index": e["index"], "system": e["system"], "chain_ids": e.get("cap_n", 1),
                                        "state": o["state"], "confidence": o["confidence"]})
            intents.sort(key=lambda i: (i["request_id"], i["effect_index"]))
            auth = self._gate.probe_view(c.clock.now()) if self._h29 else {"version": None, "lease_until": None}
            return {"form": FORM, "committed": committed, "intents": intents, "authority": auth,
                    "approvals_open": sorted(set(c.ledger.open_approvals()))}


def _exists(d: str, name: str) -> bool:
    import os  # noqa: PLC0415
    return os.path.exists(os.path.join(d, name))
