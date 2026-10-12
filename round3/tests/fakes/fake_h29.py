"""H29 test fakes (never registered). FakeHonestG5 = oracle-backed reference: it decides with r3_oracle (like tests/fakes/h23_fakes.py), obeys
the P1g seam (lease-backed AUTH, anchor before ack, write-ahead outbox, hard-restart rebuild, recovery_view) and exists to prove the harness
can say SUPPORTED. The known-negative fakes of ORACLE-AND-HARNESS-G5 s10 are named builds of it (mutants of r3_shared.mutants.KNOWN["H29"]
or a `mode`). It reuses the oracle on purpose: reference, not an independent check. Durable extras live in <world dir>/fakestate (copied by
the RC1 byte copy; the history store is only used for the anchor envelope, so F8 tamper cannot reach the fake's decisions)."""
from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

from r3_oracle import approvals as oracle_approvals
from r3_oracle import extoracle, ops_model
from r3_oracle.disclosure import low_view
from r3_oracle.disclosure_reads import expected_list_objects, expected_read_object
from r3_shared import mutants as mutants_mod
from r3_shared.authsvc import Lease, validate_lease
from r3_shared.extadapter import correlation
from r3_shared.extsystems import idempotency, observability, render_target
from r3_shared.faultplane import CanonicalStateLost, DependencyUnavailable
from r3_shared.recovery import DEP_UNAVAILABLE, IN_DOUBT, validate_recovery_view
from r3_shared.variant import CallResult
from tests.fakes import fake_h28_adapt as A
from tests.fakes.fake_h28 import H28Dep

_MODULE_CACHE: dict = {}      # FakeSurvivesCoopCrash: dies with the process (a hard kill)


class H29Dep(H28Dep):
    def __init__(self, domain, factory, verifier, ops, auth, clock, mutants, history, anchor, external, authority_source, resume, mode):
        w0 = factory("fake-service")
        wpath = w0._con.execute("PRAGMA database_list").fetchone()[2]
        w0.close()
        sd = Path(wpath).parent / "fakestate"
        if resume and not sd.exists() and mode != "empty_on_loss":
            raise CanonicalStateLost("fake state absent")
        sd.mkdir(exist_ok=True)
        self.history, self.anchor, self.authority_source, self.fmode = history, anchor, authority_source, mode
        self._restarted, self._auth_up, self._lease, self.sdir = resume, None, None, sd
        super().__init__(domain, factory, verifier, ops, auth, clock, frozenset(mutants), str(sd), external, "honest")
        self.audience = "fake"
        self.prepared = json.loads((sd / "prepared.json").read_text()) if (sd / "prepared.json").exists() else {}
        p = sd / "lease.json"
        self._lease = validate_lease(json.loads(p.read_text())) if p.exists() else None
        self.stream = self._stream()
        self.approved = json.loads((sd / "approvals.json").read_text()) if (sd / "approvals.json").exists() else {}
        if resume:
            self._promote()
            if "outbox_dropped_on_restart" in self.mutants:
                for it in self.g4["intents"]:
                    if not it["attempts"]:
                        it["done"] = True
                        self.g4["outcomes"][f"{it['request_id']}#{it['effect_index']}"].update(state="RECONCILED_FAILED", evidence=[])
                self._g4_save()

    # ---- durable helpers ------------------------------------------------------------------------------------------
    def _w(self, name, obj):
        (self.sdir / name).write_text(json.dumps(obj, sort_keys=True))

    def _stream(self) -> str:
        raw = self.history.get("meta/stream") if self.history is not None else None
        if raw:
            return raw.decode()
        s = f"fake-h29-{self.domain}-{self.clock.now()}"
        if self.history is not None:
            self.history.put("meta/stream", s.encode())
        return s

    def _commit_rows(self):
        return [(seq, json.loads(dj)) for seq, dj in self.world._con.execute(
            "SELECT seq, data_json FROM world_log WHERE kind='mark' AND ref='commit' ORDER BY seq")]

    def _promote(self):
        done = {d["request_id"] for _, d in self._commit_rows()}
        have = {i["request_id"] for i in self.g4["intents"]}
        for rid, p in sorted(self.prepared.items()):
            if rid in done and rid not in have:
                self._record_at(rid, p["ext"], p["had"], p["tick"])
        self.prepared = {}
        self._w("prepared.json", {})

    def _record_at(self, rid, ext, had, tick):
        b = self.external
        for i, e in enumerate(ext):
            s, op = e["adapter"], e["target"]
            target = render_target(b.systems["systems"][s]["operations"][op]["target_rule"], e["payload"])
            it = {"request_id": rid, "effect_index": i, "system": s, "operation": op, "target": target, "payload": e["payload"],
                  "class": idempotency(b.systems, s, op), "commit_tick": tick, "attempts": 0, "done": False, "approved": bool(had), "reply": None}
            it["cap"] = A.cap_for(b.root_caps[s], it, tick, b.window)
            self.g4["intents"].append(it)
            obs = observability(b.systems, s)
            self.g4["outcomes"][f"{rid}#{i}"] = {"request_id": rid, "effect_index": i, "system": s, "evidence": [],
                                                 "state": "UNKNOWN" if obs == "none" else "PENDING", "confidence": "full" if obs == "full" else "low"}
        self._g4_save()

    # ---- dependencies ---------------------------------------------------------------------------------------------
    def _dep(self, node):
        if self.fmode == "always_unavailable":
            node = "AUTH"
        if self.fmode == "misattribute" and node == "AUTH":
            node = "ANCHOR"
        if "dependency_failure_as_denial" in self.mutants:
            return CallResult("DENIED", {"reason": "not_authorized"})
        return CallResult("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": node})

    def _auth(self):
        try:
            lease = self.authority_source.client.fetch()
            self._auth_up = True
            self._lease = lease
            self._w("lease.json", {"digest": lease.digest, "doc": lease.doc, "granted_tick": lease.granted_tick,
                                   "lease_until": lease.lease_until, "mac": lease.mac})
            _MODULE_CACHE["lease"] = lease
            return lease, None
        except DependencyUnavailable:
            self._auth_up = False
            l = self._lease
            if l is not None and ("fail_open_on_authority_outage" in self.mutants
                                  or ("stale_cache_after_restart" in self.mutants and self._restarted) or l.valid_at(self.clock.now())):
                return l, None
            return None, self._dep("AUTH")

    def _anchor_up(self):
        try:
            self.anchor.head(self.stream)
            return True
        except DependencyUnavailable:
            return False

    def _halted(self):
        """global_halt_on_fault: ANY dependency fault stops every request."""
        if "global_halt_on_fault" not in self.mutants and self.fmode != "always_unavailable":
            return None
        if self.fmode == "always_unavailable":
            return self._dep("AUTH")
        try:
            self.authority_source.client.fetch()
        except DependencyUnavailable:
            return self._dep("AUTH")
        return None if self._anchor_up() else self._dep("ANCHOR")

    # ---- decision plane -------------------------------------------------------------------------------------------
    def _pre(self, name, args):
        op = ops_model.op_of(self.ops, name)
        if op is None:
            return CallResult("INVALID", {"reason": "unknown_operation"}), None
        ok, _, _ = ops_model.validate_args(op, args)
        return (CallResult("INVALID", {"reason": "schema_invalid"}) if not ok else None), op

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None):
        if self._sub(token) is None:
            return CallResult("DENIED", {"reason": "bad_token"})
        bad, _ = self._pre(name, args)
        if bad is not None:
            return bad
        h = self._halted()
        if h is not None:
            return h
        lease, rep = self._auth()
        if rep is not None:
            return rep
        self.auth = lease.doc
        if name not in {t.name for t in self.tools(token)}:
            return CallResult("UNKNOWN", {"reason": "unknown_tool"})
        return self._run(token, name, args, on_behalf_of, request_id, backstop=False)

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        if self._sub(token) is None:
            return CallResult("DENIED", {"reason": "bad_token"})
        bad, _ = self._pre(operation, args)
        if bad is not None:
            return bad
        h = self._halted()
        if h is not None:
            return h
        lease, rep = self._auth()
        if rep is not None:
            return rep
        self.auth = lease.doc
        return self._run(token, operation, args, on_behalf_of, request_id, backstop=True)

    def _run_locked(self, token, op, args, obo, rid, backstop):
        sub = self._sub(token)
        if rid is not None:
            done = [(sq, d) for sq, d in self._commit_rows() if d.get("request_id") == rid]
            if done:                                                          # replay: the ack still waits for its anchor entry (R27-6)
                return self._anchored(rid, done[0][0], self.clock.now(), CallResult("OK", {"replayed": True}))
        if not self._anchor_up() and "anchor_skipped_when_unavailable" not in self.mutants:
            return self._dep("ANCHOR")
        snap, akey = self.world_snapshot(), oracle_approvals.key(sub, obo, op, args)
        out = ops_model.evaluate(self.ops, self.auth, sub, obo, op, args, snap, self.clock.now(), approved=self.approved.get(akey, 0) > 0)
        if out.kind == ops_model.NEEDS_APPROVAL:
            return CallResult("DENIED", {"reason": "approval_required"})
        if out.kind != ops_model.COMMIT:
            return CallResult({"DENIED_AUTHORITY": "DENIED", "DENIED_RULE": "DENIED", "INVALID": "INVALID", "UNKNOWN_OP": "UNKNOWN"}[out.kind],
                              {"reason": str(out.detail or "refused")})
        ext = [e for e in out.effects if e["kind"] == "external"]
        if out.used_approval:
            self.approved[akey] -= 1
            self._w("approvals.json", self.approved)
        if ext and rid is not None and self.external is not None:
            self.prepared[rid] = {"ext": ext, "had": bool(out.used_approval), "tick": self.clock.now()}
            self._w("prepared.json", self.prepared)          # write-ahead: promoted at commit / on resume
        with self.world.transaction(tag="effect") as tx:
            for e in out.effects:
                if e["kind"] in ("create", "update", "link", "unlink", "delete"):
                    self._apply_one(e)
            seq = tx.mark("commit", {"request_id": rid, "kind": "direct", "authority_version": self._doc_digest()})
        if ext and rid is not None and self.external is not None:
            self._record_at(rid, ext, bool(out.used_approval), self.clock.now())
            self.prepared.pop(rid, None)
            self._w("prepared.json", self.prepared)
        if "anchor_skipped_when_unavailable" in self.mutants and not self._anchor_up():
            return CallResult("OK", {"op": op})
        return self._anchored(rid, seq, tx.tick, CallResult("OK", {"op": op}))

    def _doc_digest(self):
        return hashlib.sha256(json.dumps(self.auth, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    def _apply_one(self, e):
        w, k = self.world, e["kind"]
        t, key = (e["ref"].split(":", 1) + [""])[:2] if k in ("create", "update", "delete") else ("", "")
        try:
            if k == "create":
                w.create(t, key, e["props"])
            elif k == "update":
                w.update(t, key, {f: nv for f, (_, nv) in e["changes"].items() if nv is not None})
            elif k == "link":
                w.link(*e["ref"].split("|"))
        except Exception:  # noqa: BLE001 - WorldConflict on a no-op effect
            pass

    def _anchored(self, rid, seq, tick, ok):
        if self.anchor is None or rid is None:
            return ok
        head = None
        try:
            if self.anchor.lookup(self.stream, rid) is not None:
                return ok
            head = self.anchor.head(self.stream)
            n = (head["seq"] if head else 0) + 1
            raw = json.dumps({"rid": rid, "seq": seq, "tick": tick, "n": n}, sort_keys=True).encode()
            self.anchor.append(self.stream, n, rid, hashlib.sha256(raw).hexdigest())
            if self.history is not None:
                self.history.put(f"env/{n:08d}", raw)
        except DependencyUnavailable:
            return CallResult("UNKNOWN", {"reason": IN_DOUBT})
        return ok

    # ---- reads / approvals --------------------------------------------------------------------------------------
    def read(self, token, operation, args):
        sub = self._sub(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "bad_token"})
        h = self._halted()
        if h is not None:
            return h
        lease, rep = self._auth()
        if rep is not None:
            return rep
        lv = low_view(self.world_snapshot(), lease.doc, sub, self.ops)
        st, body = (expected_read_object(lv, f"{args['type']}:{args['key']}") if operation == "get" else expected_list_objects(lv, args.get("type", "")))
        return CallResult(st, body)

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        if self._sub(token) is None:
            return CallResult("DENIED", {"reason": "bad_token"})
        lease, rep = self._auth()
        if rep is not None:
            return rep
        self.auth = lease.doc
        return super().approve(token, operation, args, requester, on_behalf_of)

    def delegate(self, token, edge, request_id):
        return CallResult("INVALID", {"reason": "schema_invalid"})

    def revoke(self, token, edge_id, request_id):
        return CallResult("INVALID", {"reason": "unknown_edge"})

    # ---- outbox ---------------------------------------------------------------------------------------------------
    def dispatch_pending(self):
        before = {i["request_id"] + "#" + str(i["effect_index"]): i["attempts"] for i in self.g4["intents"]}
        res = super().dispatch_pending()
        for it in self.g4["intents"]:
            r = it.get("reply")
            if r is None and it["attempts"] > before.get(f"{it['request_id']}#{it['effect_index']}", 0):
                it["attempts"] = before.get(f"{it['request_id']}#{it['effect_index']}", 0)      # a dependency outage is not an attempt
        self._g4_save()
        return res

    def replay(self, decision_id):
        from r3_shared.variant import ReplayResult
        return ReplayResult("UNRESOLVED", "unknown_decision")

    # ---- G5 self-reports ----------------------------------------------------------------------------------------
    def _report_lease(self):
        l = self._lease
        if l is None:
            return None
        if "stale_cache_after_restart" in self.mutants and self._restarted:
            return l
        return l if l.valid_at(self.clock.now()) else None

    def recovery_view(self) -> dict:
        marks = [{"request_id": d.get("request_id"), "world_seq": seq, "authority_version": d["authority_version"]} for seq, d in self._commit_rows()]
        salt = random.Random(os.getpid()).random() < 0.5
        intents = []
        for i in sorted(self.g4["intents"], key=lambda x: (x["request_id"], x["effect_index"])):
            o = self.g4["outcomes"][f"{i['request_id']}#{i['effect_index']}"]
            st = o["state"]
            if "nondeterministic_recovery" in self.mutants and st in ("PENDING", "UNKNOWN") and salt:
                st = "UNKNOWN" if st == "PENDING" else "PENDING"
            intents.append({"request_id": i["request_id"], "effect_index": i["effect_index"], "system": i["system"], "chain_ids": 1,
                            "state": st, "confidence": o["confidence"]})
        l = self._report_lease()
        return validate_recovery_view({"form": "r3-recovery-1", "committed": marks, "intents": intents,
                                       "authority": {"version": None if l is None else l.digest, "lease_until": None if l is None else l.lease_until},
                                       "approvals_open": sorted(hashlib.sha256(k.encode()).hexdigest() for k, n in self.approved.items() if n > 0)})

    def dependency_status(self) -> dict:
        return {"AUTH": "UNKNOWN" if self._auth_up is None else ("UP" if self._auth_up else "DOWN")}

    def authority_version(self):
        return self._doc_digest()

    def arm_crash(self, point):
        raise NotImplementedError("hard crashes only (P1g-6)")

    def crash(self):
        raise NotImplementedError("hard crashes only (P1g-6)")

    def restart(self):
        raise NotImplementedError("hard crashes only (P1g-6)")


class FakeHonestG5:
    name = "fake-h29-honest"
    audience = "fake"
    MODE = "honest"
    MUTANTS: tuple = ()

    def __init__(self, mutants=()):
        self.mutants = mutants_mod.validate(tuple(mutants) + self.MUTANTS)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None,
               governance=None, external=None, authority_source=None, resume=False):
        return H29Dep(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, self.mutants, history, anchor, external,
                      authority_source, resume, self.MODE)


def _named(cls_name: str, mutants=(), mode="honest"):
    return type(cls_name, (FakeHonestG5,), {"MUTANTS": tuple(mutants), "MODE": mode, "name": f"fake-h29-{cls_name}"})


FakeFailOpenAuth = _named("FakeFailOpenAuth", ("fail_open_on_authority_outage",))
FakeGlobalHalt = _named("FakeGlobalHalt", ("global_halt_on_fault",))
FakeStaleRestart = _named("FakeStaleRestart", ("stale_cache_after_restart",))
FakeRandomRecovery = _named("FakeRandomRecovery", ("nondeterministic_recovery",))
FakeDenyOnOutage = _named("FakeDenyOnOutage", ("dependency_failure_as_denial",))
FakeDropOutbox = _named("FakeDropOutbox", ("outbox_dropped_on_restart",))
FakeAckBeforeAnchor = _named("FakeAckBeforeAnchor", ("anchor_skipped_when_unavailable",))
FakeAlwaysUnavailable = _named("FakeAlwaysUnavailable", (), "always_unavailable")
FakeMisattributes = _named("FakeMisattributes", (), "misattribute")
FakeSurvivesCoopCrash = _named("FakeSurvivesCoopCrash", (), "honest")      # module cache only a cooperative crash could keep: 0 classes
