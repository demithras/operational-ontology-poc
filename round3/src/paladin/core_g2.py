"""Gate 2 part of the request core: decisions, capability-edge authority, authority mutations (delegate / revoke /
set_authority) and the history/anchor plumbing. Mixed into `paladin.core.Core` (which keeps the H23 request path).

Every authority mutation and every effect commit happens inside ONE world write transaction (`WorldHandle.transaction`) with
the marks of PROT-H24 s4: `authority` {op, ...} (mutations) and `commit` {request_id, kind, authority_version} (all).
"""
from __future__ import annotations

import copy
import json
import threading
from typing import Any

from paladin import capgraph, evid
from paladin.engine import gates
from paladin.prov import Prov
from paladin.worldbridge import log_head, tx_rows
from r3_shared.authgraph import V2, V3, authority_digest
from r3_shared.authspec import validate_strict
from r3_shared.evidence import canonical_bytes
from r3_shared.variant import CallResult

# gate (of a refusal) -> reason code recorded in the decision; refusals from any other gate are not governed decisions
GOVERNED = {"authority": "authority", "delegation": "delegation", "surface": "authority", "approval": "approval",
            "policy": "policy", "gate_pass": "gate_pass", "preconditions": "preconditions", "hard_constraints": "constraints",
            "governance": "governance"}
RULE_INVALID = {"preconditions", "constraints"}  # INVALID refusals that are rule verdicts (the rest are schema/engine faults)
ISSUE_STATUS = {"INVALID": "INVALID", "DENIED": "DENIED"}


class Rollback(Exception):
    def __init__(self, result: CallResult):
        self.result = result


class G2Mixin:
    def g2_init(self, history, anchor, stream, mutants) -> None:
        self.history, self.anchor = history, anchor
        self.prov = Prov(history, anchor, stream, mutants) if history is not None and anchor is not None else None
        self._hcache: dict = {}
        self._cand: dict = {}      # version-bound candidate paths: (authority version, subject, obo) -> paths
        self._dcache: dict = {}    # MUTANT stale_authority_cache: final decisions keyed WITHOUT the version
        self._deferred: list = []  # MUTANT revoke_commit_reorder: acknowledged-but-unapplied revocations
        self.owner = {}
        for o in self.ops_spec["operations"]:  # the handle whose transaction commits an operation's effects
            sys_ = sorted({e["adapter"] for e in o["effects"] if e["kind"] == "external"})
            self.owner[o["name"]] = sys_[0] if sys_ else "paladin-service"

    def handle(self, name: str):
        """One cached WorldHandle per writer (the adapters write through the handle that owns the open transaction).
        MUTANT unsynchronized_commit: one handle per thread, so the unsynchronised commits really overlap in the world store."""
        k = (name, threading.get_ident()) if "unsynchronized_commit" in self.mutants else name
        h = self._hcache.get(k)
        if h is None:
            h = self._hcache[k] = self._factory(name)
        return h

    # ---- authority document ----------------------------------------------------------------
    lease_version = None   # Gate 5 (authority_source given): digest of the AuthorityService document adopted; None on the legacy path

    def version(self) -> str:
        return authority_digest(self.auth)

    def stamp(self, doc=None) -> str:
        """The authority version a commit is bound to: the AuthorityService version in force (H29 path) else the digest of `doc`."""
        return self.lease_version or (self.version() if doc is None else authority_digest(doc))

    def pdefs(self) -> dict:
        return {p["id"]: p for p in self.auth["principals"]}

    def persist(self, doc: dict) -> None:
        self.ledger.put_meta("auth_spec", doc)
        if self.history is not None:
            self.history.put(f"auth/{authority_digest(doc)}", canonical_bytes(doc))

    def replace_authority(self, spec: dict, keep_edges: bool = False) -> None:
        """set_authority: validate, then one transaction {mark authority set_authority; boot; persist}. ValueError changes nothing."""
        if self.auth_fault is not None:
            raise ValueError("authority history unresolved")
        validate_strict(spec, self.ops_spec)
        inforce = bool(self.auth.get("capabilities") or self.auth.get("revoked"))
        kinds = (V2, V3) if keep_edges else (V2,)   # keep_edges: the Gate 5 lease adoption path keeps v3 edges too
        if self.auth.get("spec") in kinds and (inforce or spec.get("spec") in kinds):  # E-5: base layer only; edges and revocations in force persist, the doc's are ignored
            spec = {"max_delegation_depth": self.auth["max_delegation_depth"], **copy.deepcopy(spec), "spec": self.auth["spec"] if keep_edges else V2, "capabilities": copy.deepcopy(list(self.auth.get("capabilities", ()))),
                    "revoked": sorted(self.auth.get("revoked", ()))}
            validate_strict(spec, self.ops_spec)
        with self._svc.transaction(tag="authority") as tx:
            tx.mark("authority", {"op": "set_authority", "version": self.lease_version or authority_digest(spec)})
            self.install(spec)

    # ---- decisions -------------------------------------------------------------------------
    def new_decision(self, kind: str, sub: str, obo: Any, op: str, args: Any, rid: Any, art_op: Any = "same") -> dict:
        return {"kind": kind, "sub": sub, "obo": obo, "op": op, "args": args, "rid": rid, "ops_spec": self.ops_spec,
                "art_op": op if art_op == "same" else art_op, "path": [], "rows": [], "world_seq": None, "tick": None,
                "evidence": None, "doc": None, "reason": None}

    @staticmethod
    def decision_args(kind: str, payload: Any) -> Any:
        """E-4 args_digest subject: the edge dict for delegate, the edge_id STRING for revoke."""
        return payload.get("edge_id") if kind == "revoke" and isinstance(payload, dict) else payload

    def evidence_for(self, op: str, args: Any) -> list:
        return evid.evidence_objects(self.ops_spec, op, args, self._svc.get, self._svc.list)

    def finish(self, d: dict, res: CallResult) -> CallResult:
        """Bind, chain and anchor the decision (anchor-before-ack, R27-6) when it is a governed decision."""
        if self.prov is None:
            return res
        if d["op"] is not None and self.schema_problem(d["op"], d["args"]) is not None:
            return res  # E-9: a schema-INVALID request is never a governed decision, whatever gate answered first
        if res.status == "OK":
            reason = "ok"
        elif res.status in ("DENIED", "INVALID"):
            reason = d["reason"] or GOVERNED.get(res.body.get("gate"))
            if res.status == "INVALID":  # E-8: every INVALID is governed unless the ops-spec input schema refuses the request
                if d["op"] is None:  # delegate / revoke: schema faults carry no reason code (PROT-H24 s2)
                    if reason is None:
                        return res
                elif self.schema_problem(d["op"], d["args"]) is not None:
                    return res
                reason = reason or str(res.body.get("gate") or "invalid")
            elif reason is None:
                return res
        else:
            return res
        d["status"], d["reason"] = res.status, reason
        if d["world_seq"] is None:
            d["world_seq"], d["tick"], d["rows"] = log_head(self._svc), self.clock.now(), []
        if d["evidence"] is None:
            d["evidence"] = self.evidence_for(d["art_op"], d["args"]) if d["art_op"] else []
        if d["doc"] is None:
            d["doc"] = self.auth
        err = self.prov.record(d)
        if err == "float_in_artifact":
            return CallResult("INVALID", {"reason": err})
        if not err:
            if res.status == "OK":
                self.pend_drop(d["rid"])
            self.note_decision(d, res)  # PROT-H26 s4: what the provenance views need about this anchored decision
        return CallResult("UNAVAILABLE", {"reason": err}) if err else res

    def schema_problem(self, op: Any, args: Any) -> str | None:
        """E-8: the ops-spec INPUT SCHEMA verdict (names, required, null, scalar type) - never existence, rules or reason text."""
        o = self.ops.get(op) if isinstance(op, str) else None
        if o is None:
            return None  # not an operation request (delegate / revoke carry their own shape checks)
        return self.schema_problem_def(o, args)

    @staticmethod
    def schema_problem_def(o: dict, args: Any) -> str | None:
        """The same E-8/E-9 verdict for any operation-shaped definition (also the emergency:declare pseudo-operation)."""
        if not isinstance(args, dict):
            return "args must be an object"
        names = {i["name"]: i for i in o["inputs"]}
        for k in args:
            if k not in names:
                return f"unknown argument {k}"
        for n, i in names.items():
            if n not in args:
                if i["required"]:
                    return f"missing {n}"
                continue
            v = args[n]
            t = i["type"]
            if v is None:
                return f"null {n}" if i["required"] else None  # E-9: null is "missing" - fatal only for a required input
            if t == "resource" and isinstance(v, str) and v.strip() == "":
                return f"blank {n}"
            ok = (isinstance(v, int) and not isinstance(v, bool)) if t == "integer" else \
                isinstance(v, (int, float)) and not isinstance(v, bool) if t == "number" else \
                isinstance(v, bool) if t == "boolean" else isinstance(v, str) if t in ("string", "resource") else True
            if not ok:
                return f"type {n}"
        return None

    def refuse(self, sub: str, obo: Any, op: str, args: Any, rid: Any, res: CallResult, kind: str) -> CallResult:
        """A refusal decided before the commit path (surface / delegation): still a governed decision when it is an authority verdict."""
        clean = self.check_shape(op, args, rid) if op in self.ops else res
        if isinstance(clean, CallResult):
            return res  # a malformed request is refused exactly as before and is not a governed decision
        d = self.new_decision(kind, sub, obo, op, clean, rid)
        d["reason"] = "no_valid_path" if res.body.get("reason") == "no_valid_path" else None
        with self._guard():
            out = self.finish(d, res)
            self.record_refusal(d, out, sub, obo, op, clean, rid, False)   # G5-E35 B1 (H29): a redelivery returns this refusal
            return out

    # ---- edge-mode requests (PROT-H24 s3) -----------------------------------------------------
    def candidates(self, sub: str, obo: str) -> list:
        k = (authority_digest(self.auth), sub, obo)
        if k not in self._cand:
            if len(self._cand) > 4096:
                self._cand.clear()
            self._cand[k] = capgraph.candidates(self.auth, sub, obo)
        return self._cand[k]

    def edge_check(self, sub: str, obo: str, op: str, args: dict, tick: int, d: dict) -> CallResult | None:
        R = evid.input_refs(self.ops_spec, op, args)
        key = (sub, obo, op, tuple(R))
        if "stale_authority_cache" in self.mutants and key in self._dcache:  # MUTANT: cached, never invalidated
            path = self._dcache[key]
        else:
            spec = self.eng.model.get("actions", op)
            res = gates.resources_of(self.eng, spec, args)

            def deny(pid: str) -> bool:
                p = self.booted.principals.get(pid)
                return p is not None and bool(self.eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=p,
                                                                capability=f"action:{op}", resources=res,
                                                                view=self.eng.read_view()).deny)
            path = capgraph.find_path(self.auth, self.candidates(sub, obo), op, R, tick, deny, self.mutants)
            if "stale_authority_cache" in self.mutants:
                self._dcache[key] = path
        d["path"] = list(path or [])
        if path is None:
            d["reason"] = "no_valid_path"
            return CallResult("DENIED", {"gate": "delegation", "reason": "no_valid_path"})
        return None

    def excluded_approvers(self, requester: str, obo: Any) -> set:
        out = self.chain_pids(requester)
        if obo is not None and self.delegator.get(requester) is None:
            out |= capgraph.chain_issuers(self.auth, obo, requester)
        return out

    # ---- authority mutations (PROT-H24 s2, s5) ---------------------------------------------------
    def mutate_authority(self, kind: str, sub: str, payload: Any, rid: Any) -> CallResult:
        from paladin.core import fingerprint, plain  # noqa: PLC0415 - core imports this module
        if self.auth_fault is not None:  # E-7
            return CallResult("UNAVAILABLE", {"reason": "authority_history_unresolved"})
        if not isinstance(rid, str) or not rid:
            return CallResult("INVALID", {"reason": "request_id required"})
        fp = fingerprint(sub, kind, payload)
        with self._guard():
            led = self.ledger.get(rid)
            if led is not None:
                if led["state"] != "COMMITTED":
                    return CallResult("UNAVAILABLE", {"reason": "request in flight"})
                if led["fp"] != fp:
                    return CallResult("INVALID", {"reason": "request_id already used for a different request"})
                if getattr(self, "h29", False):
                    bad = self.unacked(rid, led)
                    if bad is not None:
                        return bad
                return CallResult(led["status"], plain(led["body"] or {}))
            g = self.guard_history(rid)
            if g is not None:
                return g
            d = self.new_decision(kind, sub, None, None, self.decision_args(kind, payload), rid, art_op=None)  # E-4: operation null
            if kind == "revoke" and "revoke_commit_reorder" in self.mutants:  # MUTANT: acknowledge now, apply after the next effect
                bad = capgraph.check_revoke(self.auth, payload.get("edge_id") if isinstance(payload, dict) else None, sub)
                if bad is None:
                    self._deferred.append((sub, payload, rid, fp))
                    self.ledger.commit_row(rid, fp, sub, None, kind, "OK", {})
                    return CallResult("OK", {})
            return self.apply_authority(kind, sub, payload, rid, fp, d)

    def apply_authority(self, kind: str, sub: str, payload: Any, rid: str, fp: str, d: dict) -> CallResult:
        edge_id = payload.get("edge_id") if kind == "revoke" else None
        persisted = False
        prev = self.auth
        try:
            with self._svc.transaction(tag="authority") as tx:
                if kind == "delegate":
                    bad = capgraph.check_issue(self.auth, payload, sub, tx.tick, self.pdefs(), self.mutants)
                else:
                    bad = capgraph.check_revoke(self.auth, edge_id, sub)
                if bad is not None:
                    status, reason = bad
                    body = {"already": True} if status == "OK" else {"reason": reason}
                    d["reason"], d["rule_invalid"] = (None if status == "OK" or reason == "schema" else reason), True
                    raise Rollback(CallResult(status, body))
                new = capgraph.with_edge(self.auth, payload) if kind == "delegate" else capgraph.with_revoked(self.auth, edge_id)
                ver = self.stamp(new)
                tx.mark("authority", {"op": kind, **({"edge": payload} if kind == "delegate" else {"edge_id": edge_id}),
                                      "version": ver})
                seq = tx.mark("commit", {"request_id": rid, "kind": kind, "authority_version": ver})
                body = {"edge_id": payload["id"]} if kind == "delegate" else {}
                d.update(doc=new)
                self.pend_put(d)
                self.hook("before_commit")  # armed crash: the transaction rolls back, the change is absent
                self.persist(new)  # durable before the world commit completes; undone below on any failure
                persisted = True
                self.ledger.commit_row(rid, fp, sub, None, kind, "OK", body)
                self.ledger.put_meta(f"used:{rid}", {"authority_version": ver, "world_seq": seq, "tick": tx.tick, "path": [],
                                                      "on_behalf_of": None})
                d.update(world_seq=seq, tick=tx.tick, rows=tx_rows(self._svc, tx.id), doc=new)
            self.auth = new
        except Rollback as r:
            self.ledger.commit_row(rid, fp, sub, None, kind, r.result.status, r.result.body) if r.result.status == "OK" else None
            return self.finish(d, r.result)
        except BaseException as exc:
            from paladin.core import Crash  # noqa: PLC0415
            if persisted and not isinstance(exc, Crash):
                self.persist(prev)
                self.ledger.drop(rid)
            raise
        self.hook("after_commit")  # armed crash: the authority change is effective, the ack is lost
        return self.finish(d, CallResult("OK", body))

    def flush_deferred(self) -> None:
        """MUTANT revoke_commit_reorder: apply the acknowledged revocations after an effect committed."""
        pending, self._deferred = self._deferred, []
        for sub, payload, rid, fp in pending:
            self.apply_authority("revoke", sub, payload, rid, fp, self.new_decision("revoke", sub, None, None, self.decision_args("revoke", payload), rid, None))

    # ---- H29 / G5-E12: the decision of a commit is journaled BEFORE the world COMMIT so a lost anchor entry can be completed later ----
    PEND = "led/pend/"

    _PEND_DDL = ("CREATE TABLE IF NOT EXISTS pal_pend(request_id TEXT PRIMARY KEY, rec_json TEXT NOT NULL, "
                 "anchored INTEGER NOT NULL DEFAULT 0)")

    def pend_put(self, d: dict, th=None) -> None:
        """Durable record of everything the missing anchor entry needs (the pre-commit evidence and document cannot be re-read after the fact).
        H30-pilot M3: the copy anchor completion trusts lives in the WORLD DB, written in the commit's own transaction (rolled back with it);
        the HistoryStore copy is only a hint an A6 attacker can edit."""
        if not getattr(self, "h29", False) or self.prov is None or not isinstance(d.get("rid"), str):
            return
        rec = {k: d[k] for k in ("kind", "sub", "obo", "op", "args", "rid", "art_op", "path", "evidence", "doc")}
        raw = json.dumps(rec, sort_keys=True)
        h = th if th is not None else self._svc
        h._con.execute(self._PEND_DDL)
        h._con.execute("INSERT OR REPLACE INTO pal_pend(request_id, rec_json, anchored) VALUES(?,?,0)", (d["rid"], raw))
        self.history.put(self.PEND + d["rid"], raw.encode())

    def pend_world(self) -> dict:
        """request_id -> journal record (as stored in the world DB) of every commit not yet confirmed as anchored."""
        try:
            rows = self._svc._con.execute("SELECT request_id, rec_json FROM pal_pend WHERE anchored=0").fetchall()
        except Exception:  # noqa: BLE001 - no table yet: nothing was ever journaled
            return {}
        return dict(rows)

    def pend_drop(self, rid: Any) -> None:
        if getattr(self, "h29", False) and self.prov is not None and isinstance(rid, str):
            self.history.delete(self.PEND + rid)
            try:
                self._svc._con.execute("UPDATE pal_pend SET anchored=1 WHERE request_id=?", (rid,))
            except Exception:  # noqa: BLE001 - no table / world busy: the row is re-checked against the anchor next pass
                pass

    def guard_history(self, rid: str) -> CallResult | None:
        """R27-5: a request id the anchor knows as a committed decision, but whose idempotency record is gone, never commits twice."""
        if self.prov is None:
            return None
        from r3_shared.anchor import AnchorError  # noqa: PLC0415
        try:
            a = self.prov.anchored_decision(rid)
        except AnchorError:
            if "anchor_skipped_when_unavailable" in self.mutants:
                return None   # MUTANT: an unreachable anchor does not stop the commit
            return CallResult("UNAVAILABLE", {"reason": "anchor_unavailable"})
        except LookupError:
            return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
        if a is not None and a["status"] == "OK":
            return CallResult("UNAVAILABLE", {"reason": "idempotency_record_missing"})
        return None

    def unacked(self, rid: str, led: dict) -> CallResult | None:
        """H29: a stored OK is replayed only when the anchor holds the decision with a provable envelope; else UNKNOWN in_doubt
        (commit status certain, ack never anchored); an unreachable anchor is the dependency failure (str(e) names the node)."""
        if self.prov is None or led.get("status") != "OK":
            return None
        from r3_shared.anchor import AnchorError  # noqa: PLC0415
        from r3_shared.faultplane import DependencyUnavailable  # noqa: PLC0415
        try:
            a = self.prov.anchored_decision(rid)
        except DependencyUnavailable as exc:
            return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": exc.node})
        except (AnchorError, LookupError):
            return CallResult("UNKNOWN", {"reason": "in_doubt"})
        return None if a is not None and a["status"] == "OK" else CallResult("UNKNOWN", {"reason": "in_doubt"})
