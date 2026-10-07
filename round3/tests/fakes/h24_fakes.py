"""Test-only H24 fakes (never registered). FakeHonest is a reference implementation OVER THE ORACLE (correct by
construction: it exists to prove the harness can say SUPPORTED). The known-negative fakes are the same class with a
frozen H24 mutant (r3_shared.mutants.KNOWN["H24"]) or a fake-only quirk:
  fake-amplifier (non_attenuating_delegation)  fake-stalecache (stale_authority_cache)  fake-earlyack (revoke_commit_reorder)
  fake-inclusiveexpiry (expiry_inclusive)      fake-cyclegrant (quirk: accepts cycles)  fake-serializer (quirk: UNAVAILABLE
  to everyone while a revoke is in flight). `load(name, mutants)` builds a Variant."""
from __future__ import annotations

import json
import time
from pathlib import Path

from r3_oracle import authority, ops_model
from r3_oracle import approvals as oapp
from r3_oracle import scope_v2 as sc
from r3_oracle.authority_v2 import INF, RefAuthority, event
from r3_shared import mutants as mutants_mod
from r3_shared.authspec import validate_strict
from r3_shared.variant import CallResult
from tests.fakes.h23_fakes import FakeDep


class _Abort(Exception):
    def __init__(self, result):
        self.result = result


class H24Dep(FakeDep):
    QUIRKS: frozenset = frozenset()

    def __init__(self, domain, factory, verifier, ops, auth, clock, mutants=frozenset(), state_dir=None, quirks=()):
        fac = lambda w, f=factory: f("conventional-service" if w == "fake-service" else w)  # noqa: E731  allow-listed writer
        super().__init__("correct", domain, fac, verifier, ops, auth, clock, mutants, state_dir)
        self.quirks = frozenset(quirks) | self.QUIRKS
        self.ra, self.used, self.results, self.cache, self.pending = RefAuthority.from_spec(auth), {}, {}, {}, []
        self.revoking = 0
        self._load_g2()

    # -- durable state (state_dir); lost parts on crash are memory only ---------------------------------
    def _g2_file(self):
        return Path(self.state_dir) / "g2.json" if self.state_dir else None

    def _save_g2(self):
        p = self._g2_file()
        if p is not None:
            p.write_text(json.dumps({"events": [[e.seq, e.tick, e.kind, e.payload] for e in self.ra.events],
                                     "used": self.used, "results": self.results}))

    def _load_g2(self):
        p = self._g2_file()
        if p is not None and p.exists():
            d = json.loads(p.read_text())
            self.ra = RefAuthority(self.ra.base_json, tuple(event(s, t, k, json.loads(pl)) for s, t, k, pl in d["events"]))
            self.used, self.results = d["used"], d["results"]
            self.auth = self.ra.view(None).base

    def _m(self, name):
        return name in self.mutants

    def authority_version(self):
        return self.ra.digest_at(None)

    def authority_state(self):
        st = self.ra.view(None)
        return {**st.base, "capabilities": list(st.edges.values()), "revoked": sorted(st.revoked)}

    def restart(self):
        super().restart()
        self.cache, self.pending, self.revoking = {}, [], 0
        self.world = self.f("conventional-service")
        self._load_g2()

    # -- one authority transaction ---------------------------------------------------------------------
    def _auth_tx(self, kind, rid, decide, payload_of):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            return self._auth_tx_locked(kind, rid, decide, payload_of)

    def _auth_tx_locked(self, kind, rid, decide, payload_of):
        if rid in self.results:
            return CallResult("OK", self.results[rid])
        armed, self._armed = self._armed, None
        try:
            with self.world.transaction(tag="authority") as tx:
                v = decide(tx.tick)
                if v is not None and not isinstance(v, tuple):
                    raise _Abort(v)
                body, mark = v
                if body.get("already"):
                    raise _Abort(CallResult("OK", body))
                if armed == "before_commit":
                    self.crashed = True
                    raise _Abort(CallResult("UNKNOWN", {"reason": "crashed"}))
                if self._m("revoke_commit_reorder") and kind == "revoke":
                    self.pending.append((rid, decide, mark))
                    raise _Abort(CallResult("OK", body))
                seq = tx.mark("authority", {"op": kind, **mark})
                tx.mark("commit", {"request_id": rid, "kind": kind, "authority_version": self.ra.digest_at(None)})
                self.ra = self.ra.apply(event(seq, tx.tick, kind, payload_of(mark)))
        except _Abort as ab:
            return ab.result
        self.results[rid] = body
        self._save_g2()
        if armed == "after_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        return CallResult("OK", body)

    def delegate(self, token, edge, request_id):
        sub = self._sub(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "token"})

        def decide(tick):
            if isinstance(edge, dict) and edge.get("issuer") != sub:
                return CallResult("DENIED", {"reason": "not_parent_holder"})
            v = self.ra.issue_delegate(edge, INF, tick)
            soft = (self._m("non_attenuating_delegation") and v.reason in ("scope_amplification", "expiry_amplification")) \
                or ("cyclegrant" in self.quirks and v.reason == "delegation_cycle")
            if not v.ok and not soft:
                return CallResult(v.status, {"reason": v.reason})
            return {"edge_id": edge["id"]}, {"edge": edge}
        return self._auth_tx("delegate", request_id, decide, lambda m: m)

    def revoke(self, token, edge_id, request_id):
        sub = self._sub(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "token"})

        def decide(tick):
            v = self.ra.issue_revoke(sub, edge_id, INF)
            if not v.ok:
                return CallResult(v.status, {"reason": v.reason})
            return ({"already": True} if v.reason == "already" else {}), {"edge_id": edge_id}
        if "serializer" in self.quirks:  # quirk: refuse every other call while a revoke is in flight (20 ms window)
            self.revoking += 1
            try:
                time.sleep(0.02)
                return self._auth_tx("revoke", request_id, decide, lambda m: m)
            finally:
                self.revoking -= 1
        return self._auth_tx("revoke", request_id, decide, lambda m: m)

    def authority_used(self, request_id):
        rec = self.used.get(request_id)
        return CallResult("OK", rec) if rec else CallResult("INVALID", {"reason": "unknown_request"})

    def set_authority(self, spec):
        validate_strict(spec, self.ops)
        with self._lock:
            with self.world.transaction(tag="authority") as tx:
                st = self.ra.view(None)
                version = sc.digest({k: v for k, v in spec.items() if k not in ("capabilities", "revoked")},
                                    list(st.edges.values()), st.revoked)
                seq = tx.mark("authority", {"op": "set_authority", "version": version})
                self.ra = self.ra.apply(event(seq, tx.tick, "set_authority", {"spec": spec}))
            self.auth = self.ra.view(None).base
            self.cache = {} if not self._m("stale_authority_cache") else self.cache
            self._save_g2()

    # -- effects ------------------------------------------------------------------------------------------
    def _decide(self, sub, obo, op, res, tick):
        key = (sub, obo, op, tuple(res))
        if self._m("stale_authority_cache") and key in self.cache:
            return self.cache[key]
        t = tick - 1 if self._m("expiry_inclusive") else tick
        d = self.ra.decide(sub, obo, op, res, None, t)
        if not d.allow and self._m("non_attenuating_delegation") and obo is not None:
            d = self._last_edge_only(sub, obo, op, res, t) or d
        if self._m("stale_authority_cache"):
            self.cache[key] = d
        return d

    def _last_edge_only(self, sub, obo, op, res, tick):
        from r3_oracle.authority_v2 import Decision
        st = self.ra.view(None)
        for e in st.edges.values():
            if e["child"] == sub and e["id"] not in st.revoked and sc.covers(e["scope"], op, res) \
                    and (e["expires_at"] is None or tick < e["expires_at"]) \
                    and authority.decide(obo, None, op, res, st.base).allow:
                p = self.ra.edge_path(e["id"])
                if p[0]["issuer"] == obo and not any(x["id"] in st.revoked for x in p):
                    return Decision(True, "valid_path", (tuple(x["id"] for x in p),))
        return None

    def _run_locked(self, token, op, args, obo, rid, backstop):
        if self.crashed:
            return CallResult("UNAVAILABLE", {"reason": "crashed"})
        sub = self._sub(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "token"})
        if not isinstance(args, dict):
            return CallResult("INVALID", {"reason": "schema"})
        if rid is not None and rid in self.results:
            return CallResult("OK", self.results[rid])
        o = ops_model.op_of(self.ops, op)
        res = ops_model.resources_of(o, args) if o else []
        armed, self._armed = self._armed, None
        try:
            with self.world.transaction(tag="effect") as tx:
                d = self._decide(sub, obo, op, res, tx.tick)
                if not d.allow:
                    raise _Abort(CallResult("DENIED", {"reason": d.reason}))
                s, ob = (obo, None) if d.valid_paths else (sub, obo)
                akey = oapp.key(sub, obo, op, args)
                out = ops_model.evaluate(self.ops, self.ra.view(None).base, s, ob, op, args, self.world_snapshot(), tx.tick,
                                         approved=self.approved.get(akey, 0) > 0)
                if out.kind != ops_model.COMMIT:
                    raise _Abort(CallResult("DENIED" if out.kind != ops_model.INVALID else "INVALID", {"reason": out.detail}))
                if armed == "before_commit":
                    self.crashed = True
                    raise _Abort(CallResult("UNKNOWN", {"reason": "crashed"}))
                self._apply_in_tx(out.effects)
                if out.used_approval:
                    self._consume(akey)
                seq = tx.mark("commit", {"request_id": rid, "kind": "request", "authority_version": self.ra.digest_at(None)})
        except _Abort as ab:
            return ab.result
        if rid is not None:
            self.results[rid] = {"replayed": True}
            self.used[rid] = {"authority_version": self.ra.digest_at(None), "world_seq": seq, "tick": tx.tick,
                              "path": list(d.valid_paths[0]) if d.valid_paths else [], "on_behalf_of": obo}
        self._flush_pending()
        self._save_g2()
        if armed == "after_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        return CallResult("OK", {"op": op})

    def _run(self, token, op, args, obo, rid, backstop):
        if "serializer" in self.quirks and self.revoking:
            return CallResult("UNAVAILABLE", {"reason": "revoke_in_progress"})
        return super()._run(token, op, args, obo, rid, backstop)

    def _apply_in_tx(self, effects):
        w = self.world  # same transaction, same (allow-listed) writer: externals included, so the commit mark covers them
        for e in effects:
            k = e["kind"]
            t, key = (e["ref"].split(":", 1) + [""])[:2] if k in ("create", "update", "delete") else ("", "")
            if k == "create":
                w.create(t, key, e["props"])
            elif k == "update":
                w.update(t, key, {f: nv for f, (_, nv) in e["changes"].items() if nv is not None})
            elif k == "link":
                w.link(*e["ref"].split("|"))
            elif k == "external":
                w.external_write(e["adapter"], e["target"], e["payload"])

    def _flush_pending(self):  # revoke_commit_reorder: acknowledge-then-apply, after the next effect commit
        pend, self.pending = self.pending, []
        for rid, _, mark in pend:
            with self.world.transaction(tag="authority") as tx:
                seq = tx.mark("authority", {"op": "revoke", **mark})
                tx.mark("commit", {"request_id": rid, "kind": "revoke", "authority_version": self.ra.digest_at(None)})
                self.ra = self.ra.apply(event(seq, tx.tick, "revoke", mark))
            self.results[rid] = {}

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        sub = self._sub(token)
        if sub is not None and on_behalf_of is not None:  # PROT-H24 s3: not Q, not an issuer on any path to the requester
            st = self.ra.view(None)
            chain = {on_behalf_of} | {x["issuer"] for e in st.edges.values() if e["child"] == requester
                                      for x in self.ra.edge_path(e["id"])}
            if sub in chain:
                return CallResult("DENIED", {"reason": "approver_in_chain"})
        return super().approve(token, operation, args, requester, on_behalf_of)



class H24Variant:
    audience = "fake"

    def __init__(self, name, mutants=(), quirks=()):
        self.name, self.mutants, self.quirks = name, mutants_mod.validate(mutants), frozenset(quirks)

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None):
        return H24Dep(domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants, state_dir, self.quirks)


NAMED = {"fake-honest": ((), ()), "fake-amplifier": (("non_attenuating_delegation",), ()),
         "fake-stalecache": (("stale_authority_cache",), ()), "fake-earlyack": (("revoke_commit_reorder",), ()),
         "fake-inclusiveexpiry": (("expiry_inclusive",), ()), "fake-cyclegrant": ((), ("cyclegrant",)),
         "fake-serializer": ((), ("serializer",))}


def load(name, mutants=()):
    m, q = NAMED[name]
    return H24Variant(name, tuple(m) + tuple(mutants), q)
