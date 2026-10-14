"""Gate 5 behaviour of the conventional service (PROTOCOL-P1g, PROT-H29). Mixed into Service; every method is a no-op when the
service was deployed WITHOUT an authority_source (legacy H23-H28 path, unchanged).

Lease-backed authority (R29-0/R29-1): every governed decision fetches (renews) the lease while AUTH is reachable and may
decide under the held lease until lease_until (strict). Past it, or with no lease (a fresh process never trusts a durable
copy), the decision is UNAVAILABLE dependency_unavailable AUTH. Never "last known good", never fail-static.
"""
from __future__ import annotations

import json

from r3_shared.anchor import AnchorError
from r3_shared.authgraph import authority_digest
from r3_shared.authsvc import AuthorityError, Lease
from r3_shared.evidence import canonical_bytes
from r3_shared.faultplane import DependencyUnavailable
from r3_shared.recovery import FORM
from r3_shared.variant import CallResult

from . import g5journal
from .abort import _Abort
from .histledger import LedgerUnresolved, rid_key
from .g5deps import BulkheadFull, DepGraph, Guard, unavailable
from .models_gen import OPERATION_MODELS
from .pdp import Pdp
from .provenance import DecisionCtx, has_float
from .validation import RequestInvalid
from . import authdoc

DURABLE_CACHE_MAC = "durable-cache"
# authority refusals: decided from the authority document alone, so the recorded refusal stays the answer on redelivery
AUTH_REFUSALS = frozenset({"no_matching_allow", "no_matching_allow_or_denied", "on_behalf_of_not_delegator", "unknown_principal",
                           "unknown_delegator", "no_delegation", "denied_by_deny_grant", "no_delegable_grant",
                           "delegator_not_allowed", "no_valid_path", "tool_not_available"})


def denial_key(rid: str) -> str:
    return "deny/" + rid_key(rid).split("/", 1)[1]


class G5State:
    def __init__(self, source, domain, clock, mutants):
        self.source, self.graph = source, DepGraph(source.graph)
        self.guard = Guard(self.graph, domain, clock, mutants)
        self.lease: Lease | None = None
        self.adopted: str | None = None
        self.dirty = True   # journal may hold un-anchored decisions (after a resume or an in-doubt finalize)


class G5Ops:
    # -- the gate -----------------------------------------------------------------------------------------------------
    def _g5_pregate(self, kind: str, name: str | None, operation=None, args=None, obo=None, request_id=None, tool=False):
        """None = proceed. Else the reply: input errors decidable without AUTH stay INVALID (frozen names), every other
        blocked decision is UNAVAILABLE dependency_unavailable <node> with zero effects."""
        if self._g5 is None:
            return None
        blocked = self._g5_blocked(name, "read" if kind == "read" else None)
        if blocked is None:
            return None
        return self._g5_input_invalid(kind, operation, args, obo, request_id, tool) or blocked

    def _g5_blocked(self, name: str | None, surface: str | None):
        g = self._g5
        if self.mutant("global_halt_on_fault"):   # BUG: any tripped breaker stops every request, related or not
            node = g.guard.tripped()
            if node is not None:
                return unavailable(node)
        for node in g.graph.decision_nodes(self.domain, name, surface=surface):
            res = self._g5_auth() if node == "AUTH" else self._g5_anchor() if node == "ANCHOR" else None
            if res is not None:
                return res
        return None

    def _g5_gated(self) -> bool:
        return getattr(self, "_g5_in_read", False)

    def _g5_mark_gated(self, on: bool) -> None:
        self._g5_in_read = on   # guarded by the service RLock held by read()

    def _g5_input_invalid(self, kind, operation, args, obo, rid, tool):
        inv = lambda r: CallResult("INVALID", {"reason": r})  # noqa: E731
        if kind in ("execute", "approve"):
            if not isinstance(operation, str) or operation not in self._ops:
                return inv("unknown_tool" if tool else "unknown_operation")
            if obo is not None and not isinstance(obo, str):
                return inv("bad_args")
            if kind == "execute" and rid is not None and (not isinstance(rid, str) or not rid.strip()):
                return inv("bad_args")
            try:
                OPERATION_MODELS[operation].from_args(args)
            except RequestInvalid:
                return inv("schema_invalid")
            return inv("schema_invalid") if has_float(args) else None
        if kind in ("delegate", "revoke"):
            if not isinstance(rid, str) or not rid.strip():
                return inv("bad_args")
            ok = authdoc.edge_schema_ok(args) if kind == "delegate" else isinstance(args, str) and args != ""
            return None if ok else inv("schema_invalid")
        return None

    def _g5_auth(self):
        g = self._g5
        if self.mutant("stale_cache_after_restart") and g.lease is not None and g.lease.mac == DURABLE_CACHE_MAC:
            return None   # BUG: the version loaded from the durable cache after a restart is treated as in force, no lease check
        try:
            with g.guard.bulkheads["AUTH"]:
                lease = g.source.client.fetch()
        except BulkheadFull:
            return unavailable("AUTH")
        except (DependencyUnavailable, AuthorityError):
            g.guard.down("AUTH")
            now = self._clock.now()
            held = g.lease is not None and (g.lease.valid_at(now) or self.mutant("fail_open_on_authority_outage"))
            if held:   # fail_open_on_authority_outage BUG: the cached version is used whatever its lease says
                return None
            if self.mutant("dependency_failure_as_denial"):   # BUG: a dependency fault is reported as a policy denial
                return CallResult("DENIED", {"reason": "not_authorized"})
            return unavailable("AUTH")
        g.guard.up("AUTH")
        g.lease = lease
        self._g5_adopt(lease)
        return None

    def _g5_adopt(self, lease: Lease) -> None:
        """Make the leased version the policy in force: compose it with the local delegation table, make it durable and
        record the adoption (PROT-H24 s4 `authority` mark) in one world transaction."""
        g = self._g5
        if g.adopted == lease.digest:
            return
        doc = self._compose_base(lease.doc)
        digest = authority_digest(doc)
        if digest != self._policy.digest:
            h = self._factory("conventional-service")
            try:
                with h.transaction(tag="authority") as tx:
                    self._store.authority_put(h, self._policy.version + 1, doc)
                    tx.mark("authority", {"op": "adopt_lease", "version": digest, "base": lease.digest})
            finally:
                h.close()
            self._policy = Pdp(doc, self._policy.version + 1, self._mutants)
            self._dcache = {}
        g.adopted = lease.digest

    def _g5_anchor(self):
        g = self._g5
        if self.prov is None or self.mutant("anchor_skipped_when_unavailable"):   # BUG (mutant): ack now, anchor "later"
            return None
        try:
            with g.guard.bulkheads["ANCHOR"]:
                self.anchor.head(self.stream)
        except (BulkheadFull, DependencyUnavailable, AnchorError):
            g.guard.down("ANCHOR")
            return unavailable("ANCHOR")
        g.guard.up("ANCHOR")
        if g.dirty:
            self._g5_repair_anchors()
        return None

    def auth_claim(self) -> str:
        """The authority version this decision is bound to: the leased version (A(t)), else the policy digest (legacy)."""
        g = self._g5
        return g.lease.digest if g is not None and g.lease is not None else self._policy.digest

    # -- anchor journal -------------------------------------------------------------------------------------------------
    def _g5_journal(self, h, dc: DecisionCtx, status: str, body: dict, doc: dict) -> None:
        key = g5journal.key_of(dc)
        if self._g5 is not None and self.prov is not None and key is not None:
            g5journal.put(h, key, g5journal.prep_record(dc, status, body, doc))

    def _g5_complete(self, h, rid: str):
        """Finish the anchoring of a committed decision (idempotent: append, or rebuild the envelope of an entry that is
        already anchored). Returns the finalize reply, or None when nothing was open."""
        p = g5journal.get_open(h, rid)
        if p is None:
            return None
        dc = DecisionCtx(p["kind"], p["rid"], p["subject"], p["obo"], p["operation"], p["args"],
                         op=self._ops.get(p["operation"]) if isinstance(p["operation"], str) else None, governed=True,
                         evidence=[e.encode() for e in p["evidence"]], authority_doc=p["authority_doc"],
                         path=tuple(p["path"]), tick=p["tick"], world_seq=p["world_seq"], tx_id=p["tx_id"])
        dc.extra["repair"] = True
        res = CallResult(p["status"], p["body"])
        out = self.prov.finalize(h, dc, res)
        if out is res:
            g5journal.mark_done(h, rid)
        return out

    def _g5_repair_anchors(self) -> None:
        g = self._g5
        h = self._factory("conventional-service")
        try:
            for rid in g5journal.open_ids(h):
                out = self._g5_complete(h, rid)
                if out is not None and out.status != "OK":
                    return   # still in doubt: stay dirty, try again at the next governed call
            g.dirty = False
        finally:
            h.close()

    def _g5_recorded(self, rid: str, fp: str, dc: DecisionCtx):
        """G5-E35 B1 (R29-11, G5-E16): a request_id that already has a recorded decision for the SAME request gets that
        decision back - a committed OK from the idempotency ledger, an authority refusal from the denial record - before any
        authorization against the version now in force. A record that is missing/altered raises LedgerUnresolved (non-OK, zero
        effect). Nothing is written: no world row, no anchor entry. A different fingerprint falls through (key reuse)."""
        h = self._factory("conventional-service")
        try:
            with h.transaction(tag="effect"):
                prior = self._store.idem_get(h, rid)
                if prior is not None:
                    if prior[0] != fp:
                        return None
                    dc.governed, dc.extra["replayed"] = False, True
                    self._replay_anchored(h, rid)
                    return CallResult(prior[1]["status"], {**prior[1]["body"], "replayed": True})
        finally:
            h.close()
        if self.history is None:
            return None
        raw = self.history.get(denial_key(rid))
        if raw is None:
            return None
        try:
            rec = json.loads(raw)
            if not isinstance(rec, dict) or set(rec) != {"fp", "reason"} or not isinstance(rec["reason"], str):
                raise ValueError
        except ValueError as exc:
            raise LedgerUnresolved("denial record altered") from exc
        if rec["fp"] != fp:
            return None
        dc.governed, dc.extra["replayed"] = False, True
        return CallResult("DENIED", {"reason": rec["reason"], "replayed": True})

    def _g5_record_denial(self, dc: DecisionCtx, res) -> None:
        """Remember an authority refusal (a decision the world cannot change) so its redelivery is answered from the record."""
        fp = dc.extra.get("fp")
        if self._g5 is None or self.history is None or fp is None or res.status != "DENIED" or dc.extra.get("replayed") \
                or res.body.get("reason") not in AUTH_REFUSALS or not isinstance(dc.rid, str):
            return
        self.history.put(denial_key(dc.rid), canonical_bytes({"fp": fp, "reason": res.body["reason"]}))

    def _replay_anchored(self, h, rid: str) -> None:
        """A replay of a committed request_id returns the original decision only once its root is anchored."""
        if self.prov is None:
            return
        if self._g5 is None:
            if not self.prov.anchored(rid):
                raise _Abort("UNAVAILABLE", {"reason": "anchor_unavailable"})
            return
        out = self._g5_complete(h, rid)
        if out is not None and out.status != "OK":
            raise _Abort(out.status, out.body)

    # -- resume (P1g-1): nothing here touches AUTH, ANCHOR, ExternalWorld or the observer ---------------------------------
    def _g5_after_resume(self) -> None:
        g = self._g5
        if g is not None:
            g.dirty = True
            if self.mutant("stale_cache_after_restart"):   # BUG: the durable version becomes the held lease, never re-checked
                g.lease = Lease(authority_digest(self._policy.doc), self._policy.doc, 0, 2 ** 31 - 1, DURABLE_CACHE_MAC)
        if self._ext is None or not (self.mutant("outbox_dropped_on_restart") or self.mutant("nondeterministic_recovery")):
            return
        h = self._factory("conventional-service")
        try:
            if self.mutant("outbox_dropped_on_restart"):   # BUG: undelivered intents are discarded and reported as failed
                h._con.execute("UPDATE conv_outbox SET done=1 WHERE done=0")
                h._con.execute("UPDATE conv_outcome SET state='RECONCILED_FAILED' WHERE state IN ('PENDING','UNKNOWN')")
            else:   # BUG: in-doubt intents are resolved from a scan whose winner depends on a per-process random salt
                import os
                salt = os.urandom(8)
                for rid, idx in h._con.execute("SELECT request_id, effect_index FROM conv_outcome WHERE state IN ('PENDING','UNKNOWN')").fetchall():
                    pick = ("PENDING", "UNKNOWN")[hash((salt, rid, idx)) & 1]
                    h._con.execute("UPDATE conv_outcome SET state=? WHERE request_id=? AND effect_index=?", (pick, rid, idx))
        finally:
            h.close()

    # -- self reports -----------------------------------------------------------------------------------------------------
    def dependency_status(self) -> dict:
        g = self._g5
        return {} if g is None else g.guard.status()

    def recovery_view(self) -> dict:
        """RECOVERY_VIEW (P1g-8): pure SELECTs over the durable world DB, ordered by key. No dependency I/O, no mutation."""
        with self._lock:
            h = self._factory("conventional-service")
            try:
                committed = []
                for seq, raw in h._con.execute("SELECT seq, data_json FROM world_log WHERE kind='mark' AND ref='commit' ORDER BY seq"):
                    d = json.loads(raw)
                    committed.append({"request_id": d.get("request_id"), "world_seq": seq, "authority_version": d["authority_version"]})
                intents = []
                if self._ext is not None:
                    q = ("SELECT o.request_id, o.effect_index, o.system, c.state, c.confidence FROM conv_outbox o "
                         "JOIN conv_outcome c ON c.request_id=o.request_id AND c.effect_index=o.effect_index")
                    intents = sorted(({"request_id": a, "effect_index": b, "system": s, "chain_ids": 1, "state": st, "confidence": cf}
                                      for a, b, s, st, cf in h._con.execute(q)), key=lambda i: (i["request_id"], i["effect_index"]))
                approvals = sorted(set(self._store.approvals_open_all(h)))
            finally:
                h.close()
            g = self._g5
            lease = g.lease if g is not None else None
            auth = {"version": lease.digest, "lease_until": lease.lease_until} \
                if lease is not None and (lease.valid_at(self._clock.now()) or lease.mac == DURABLE_CACHE_MAC) \
                else {"version": None, "lease_until": None}
            return {"form": FORM, "committed": committed, "intents": intents, "authority": auth, "approvals_open": approvals}
