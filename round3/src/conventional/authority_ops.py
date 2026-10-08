"""Authority mutations (PROT-H24): delegate, revoke, set_authority and authority_used.

Every mutation is ONE world transaction (`WorldHandle.transaction(tag="authority")`): the new table version is made
durable, the `authority` mark and the `commit` mark are appended, and the idempotency record is written inside it. The
service lock serialises it with effect commits, so the world_log order is the linearization order (R24-3).
"""
from __future__ import annotations

import copy
import sqlite3

from r3_shared.authgraph import authority_digest
from r3_shared.authspec import validate_strict
from r3_shared.variant import CallResult

from . import authdoc, store
from .histledger import LedgerUnresolved, commit_mark
from .pdp import Pdp
from .provenance import DecisionCtx


class _NoOp(Exception):
    """Internal: a plan that is a successful no-op; unwinds the (empty) world transaction."""

    def __init__(self, body: dict):
        super().__init__("noop")
        self.body = body


class AuthorityOps:
    # -- set_authority (harness / operator surface; not a request) -----------------------------------------
    def set_authority(self, auth_spec: dict) -> int:
        validate_strict(auth_spec, self._spec)  # R-4: raise before anything changes
        with self._lock:
            if self.crashed:
                raise RuntimeError("deployment is crashed; restart() first")
            if self._authority_unresolved:
                raise RuntimeError("authority history is unresolved; refusing to extend it")
            doc = self._compose_base(auth_spec)
            new = Pdp(doc, self._policy.version + 1, self._mutants)
            h = self._factory("conventional-service")
            try:
                with h.transaction(tag="authority") as tx:
                    self._store.authority_put(h, new.version, doc)  # durable first, then swapped in
                    tx.mark("authority", {"op": "set_authority", "version": new.digest})
            finally:
                h.close()
            self._policy = new
            return new.version

    def _compose_base(self, auth_spec: dict) -> dict:
        """E-5: set_authority replaces the BASE layer only. Capability edges and revocations in force persist; any
        `capabilities`/`revoked` in the supplied document are ignored (there is no un-revoke by any path)."""
        cur = self._policy.doc
        if not authdoc.is_v2(auth_spec) and not cur.get("capabilities") and not cur.get("revoked"):
            return copy.deepcopy(auth_spec)  # pure H23 path / empty table: a v1 document stays literally what it is (E-3)
        new = authdoc.upgraded(auth_spec)
        if not authdoc.is_v2(auth_spec):  # a v1 document carries no depth bound: keep the one in force
            new["max_delegation_depth"] = cur.get("max_delegation_depth", new["max_delegation_depth"])
        new["capabilities"] = copy.deepcopy(cur.get("capabilities", []))
        new["revoked"] = list(cur.get("revoked", []))
        return new

    # -- delegate / revoke ---------------------------------------------------------------------------------
    def delegate(self, token: str, edge: dict, request_id: str) -> CallResult:
        return self._mutation(token, request_id, "delegate", {"edge": edge}, self._plan_delegate)

    def revoke(self, token: str, edge_id: str, request_id: str) -> CallResult:
        return self._mutation(token, request_id, "revoke", {"edge_id": edge_id}, self._plan_revoke)

    def _plan_delegate(self, sub, args, doc, tick):
        """-> (refusal | None, new_doc, body, mark_payload)."""
        edge, pdp = args["edge"], self._policy
        if not authdoc.edge_schema_ok(edge):
            return ("INVALID", "schema"), None, None, None
        if edge["id"] in authdoc.by_id(doc):
            return ("INVALID", "duplicate_edge"), None, None, None
        if edge["issuer"] != sub:
            return ("DENIED", "not_parent_holder"), None, None, None
        bad = authdoc.check_issue(doc, sub, edge, tick, pdp.known, pdp.is_static_delegate, pdp.root_may_delegate,
                                  skip_attenuation=self.mutant("non_attenuating_delegation"),
                                  parent_visible=lambda eid: authdoc.edge_visible(doc, eid, sub))
        if bad:
            return bad, None, None, None
        new = authdoc.add_edge(doc, edge)
        return None, new, {"edge_id": edge["id"]}, {"op": "delegate", "edge": edge}

    def _plan_revoke(self, sub, args, doc, tick):
        eid = args["edge_id"]
        if not isinstance(eid, str) or eid not in authdoc.by_id(doc) or not authdoc.edge_visible(doc, eid, sub):
            return ("INVALID", "unknown_edge"), None, None, None  # hidden == absent (PROT-H26 3.1)
        if not authdoc.revoker_ok(doc, sub, eid):
            return ("DENIED", "not_revoker"), None, None, None
        if eid in doc["revoked"]:
            return None, doc, {"already": True}, {"op": "revoke", "edge_id": eid, "noop": True}
        return None, authdoc.add_revocation(doc, eid), {}, {"op": "revoke", "edge_id": eid}

    def _mutation(self, token, request_id, kind, args, plan) -> CallResult:
        from .service import _Abort  # local: service imports this module
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._authority_unresolved:  # E-7
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            sub = self.authenticate(token)
            if sub is None:
                return CallResult("DENIED", {"reason": "token"})
            if not isinstance(request_id, str) or not request_id.strip():
                return CallResult("INVALID", {"reason": "bad_request_id"})
            # E-4: args_digest covers the edge dict (delegate) / the edge_id string (revoke), operation is null
            dc = DecisionCtx(kind, request_id, sub, None, kind, args["edge"] if kind == "delegate" else args["edge_id"],
                             governed=True)
            if kind == "delegate":  # E-9: an edge failing the v2 edge schema is schema-INVALID -> no envelope
                dc.governed = authdoc.edge_schema_ok(args["edge"])
            else:  # E-9: revoke with a non-string / empty edge_id (whitespace is governed) is schema-INVALID -> no envelope
                dc.governed = isinstance(args["edge_id"], str) and args["edge_id"] != ""
            dc.authority_doc, dc.evidence = self._policy.doc, []
            h = self._factory("conventional-service")
            try:
                try:
                    res = self._mutation_tx(h, sub, request_id, kind, args, plan, dc)
                except _Abort as a:
                    res = a.result
                except _NoOp as n:  # the open transaction rolled back: world_log and tx counter are untouched
                    res = CallResult("OK", n.body)
                except (sqlite3.Error, ConnectionError, LedgerUnresolved):
                    return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})
                if res.status == "OK" and not res.body.get("replayed") and not res.body.get("already") \
                        and self._armed == "after_commit":
                    raise_ = self._crash_now()
                    return raise_.result
                if res.body.get("replayed"):
                    res = CallResult(res.status, {k: v for k, v in res.body.items() if k != "replayed"})
                elif self.prov is not None and dc.governed and res.status in ("OK", "DENIED", "INVALID"):
                    dc.authority_doc = self._policy.doc  # authority in force at the commit point (after the mutation)
                    res = self.prov.finalize(h, dc, res)
                return res
            finally:
                h.close()

    def _mutation_tx(self, h, sub, rid, kind, args, plan, dc: DecisionCtx) -> CallResult:
        from .service import _Abort
        fp = store.fingerprint(sub, None, kind, args)
        deferred = kind == "revoke" and self.mutant("revoke_commit_reorder")
        with h.transaction(tag="authority") as tx:
            prior = self._store.idem_get(h, rid)
            if prior is not None:
                if prior[0] != fp:
                    raise _Abort("INVALID", {"reason": "idempotency_key_reuse"})
                if self.prov is not None and not self.prov.anchored(rid):
                    raise _Abort("UNAVAILABLE", {"reason": "anchor_unavailable"})
                return CallResult(prior[1]["status"], {**prior[1]["body"], "replayed": True})
            refusal, new_doc, body, mark = plan(sub, args, authdoc.upgraded(self._policy.doc), tx.tick)  # E-3: v1 == empty v2
            if refusal is not None:
                raise _Abort(refusal[0], {"reason": refusal[1]})
            if mark.get("noop"):  # PROT-H24 s5: already revoked -> OK {already:true}, no mark and NO world transaction
                raise _NoOp(body)
            if self._armed == "before_commit":
                raise self._crash_now()
            if deferred:  # BUG (revoke_commit_reorder): acknowledge now, apply after the next effect
                self._pending.append((sub, rid, args, fp))
                return CallResult("OK", body)
            version = self._apply_mutation(h, tx, rid, kind, new_doc, body, mark, sub, fp)
            dc.tx_id, dc.tick, dc.world_seq, dc.path = tx.id, tx.tick, version, ()
        self._swap_policy(new_doc)
        return CallResult("OK", body)

    def _apply_mutation(self, h, tx, rid, kind, new_doc, body, mark, sub, fp) -> int:
        """Inside the open transaction: durable table version + marks + idempotency record. Returns the commit seq."""
        digest = authority_digest(new_doc)
        self._store.authority_put(h, self._policy.version + 1, new_doc)
        tx.mark("authority", {**mark, "version": digest})
        seq = tx.mark("commit", {"request_id": rid, "kind": kind, "authority_version": digest})
        self._store.idem_put(h, rid, fp, {"status": "OK", "body": body,
                                          "used": {"authority_version": digest, "path": [], "on_behalf_of": None,
                                                   "subject": sub}})
        return seq

    def _swap_policy(self, doc: dict) -> None:
        if authority_digest(doc) != self._policy.digest:
            self._policy = Pdp(doc, self._policy.version + 1, self._mutants)

    def _drain_pending(self) -> None:
        """revoke_commit_reorder mutant only: the late application of acknowledged revocations."""
        pend, self._pending = self._pending, []
        for sub, rid, args, fp in pend:
            h = self._factory("conventional-service")
            try:
                with h.transaction(tag="authority") as tx:
                    new = authdoc.add_revocation(self._policy.doc, args["edge_id"])
                    self._apply_mutation(h, tx, rid, "revoke", new, {}, {"op": "revoke", "edge_id": args["edge_id"]}, sub, fp)
                self._swap_policy(new)
            finally:
                h.close()

    # -- authority_used (R24-6) -----------------------------------------------------------------------------
    def authority_used(self, request_id: str) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            h = self._factory("conventional-service")
            try:
                m = commit_mark(h, request_id) if isinstance(request_id, str) else None
                if m is None:
                    return CallResult("INVALID", {"reason": "unknown_request"})
                prior = self._store.idem_get(h, request_id)
                if prior is None:
                    return CallResult("INVALID", {"reason": "unknown_request"})
                u = prior[1]["used"]
                return CallResult("OK", {"authority_version": u["authority_version"], "world_seq": m[0], "tick": m[2],
                                         "path": list(u["path"]), "on_behalf_of": u["on_behalf_of"]})
            except (sqlite3.Error, LedgerUnresolved):
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            finally:
                h.close()
