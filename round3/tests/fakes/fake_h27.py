"""H27 test fakes (never registered). FakeHonest = a correct reference built on the H23 correct fake + G2 mixin that
writes the FROZEN envelope/artifacts and verifies replay against the anchor. Mutants/modes make the known negatives.
It reuses r3_oracle.provenance on purpose: it proves the harness can say SUPPORTED, it is not an independent check."""
from __future__ import annotations

import hashlib
import json

from r3_oracle import provenance as pv
from r3_shared import mutants as mutants_mod
from r3_shared.anchor import AnchorError
from r3_shared.world import WorldReader
from tests.fakes.fake_g2 import G2Mixin
from tests.fakes.fake_h27_replay import ReplayMixin
from tests.fakes.h23_fakes import FakeDep
from r3_shared.variant import CallResult

GOV = ("OK", "DENIED", "INVALID")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class HonestDep(ReplayMixin, G2Mixin, FakeDep):
    def __init__(self, mode, domain, factory, verifier, ops, auth, clock, mutants, history, anchor, paranoid=False,
                 no_anchor=False):
        FakeDep.__init__(self, "correct", domain, factory, verifier, ops, auth, clock, mutants, None)
        self.auth_spec, self.history, self.anchor = auth, history, anchor
        self.paranoid, self.no_anchor = paranoid, no_anchor
        self._g2_init(history, anchor)
        self.stream = "fake-%s-%s" % (domain, _sha(str(getattr(history, "_path", domain)).encode())[:16])
        history.put("meta/stream", self.stream.encode())
        self._path = self.world._con.execute("PRAGMA database_list").fetchone()[2]

    # -- authority document (v2 when the spec says so) ----------------------------------------------------
    def _auth_doc(self):
        a = {k: v for k, v in self.auth.items() if k not in ("capabilities", "revoked")}
        if self.auth.get("spec") == "r3-authority-2":
            return pv.authority_doc(a, self.g2["edges"], self.g2["revoked"])
        return a

    def authority_version(self):
        return _sha(pv.canon(self._auth_doc()))

    # -- approvals derived from anchored decisions only (R27-5) -------------------------------------------
    @property
    def approved(self):
        from r3_oracle import approvals
        ver = self._verified()
        ids = {d["decision_id"] for d in ver}
        out, tup = {}, {}
        for key in self.history.keys("appr/"):
            r = json.loads(self.history.get(key))
            if r["approve_decision"] in ids:
                k = approvals.key(r["requester"], r["obo"], r["operation"], r["args"])
                out[k] = out.get(k, 0) + 1
                tup[(r["requester"], r["obo"], r["operation"], pv.args_digest(r["args"]))] = k
        for d in ver:
            k = tup.get((d["subject"], d["on_behalf_of"], d["operation"], d["args_digest"]))
            if k and d["status"] == "OK" and d["kind"] in ("call_tool", "direct"):
                out[k] -= 1
        return out

    @approved.setter
    def approved(self, _v):
        pass

    def _persist_approvals(self):
        pass

    def _consume(self, akey):
        pass

    def _load_ledger(self):
        return {k[5:] for k in self.history.keys("idem/")}

    def _store_ledger(self, rid):
        self.history.put("idem/" + rid, b"1")

    # -- governed decisions --------------------------------------------------------------------------------
    def _run(self, token, op, args, obo, rid, backstop):
        kind = "direct" if backstop else "call_tool"
        return self._gov(kind, op, args, obo, rid, lambda: FakeDep._run(self, token, op, args, obo, rid, backstop),
                         token)

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        res = self._gov("approve", operation, args, on_behalf_of, None,
                        lambda: FakeDep.approve(self, token, operation, args, requester, on_behalf_of), token, requester)
        return res

    def delegate(self, token, edge, request_id):
        return self._gov("delegate", None, edge, None, request_id, lambda: G2Mixin.delegate(self, token, edge, request_id), token)

    def revoke(self, token, edge_id, request_id):
        return self._gov("revoke", None, edge_id, None, request_id, lambda: G2Mixin.revoke(self, token, edge_id, request_id), token)

    def _g2_anchor(self, request_id, kind, sub, seq, tick, body):
        return CallResult("OK", body)  # envelopes are written by _gov (all kinds, refusals included)

    def _rows(self, head):
        r = WorldReader(self._path)
        try:
            return r.log(head), r.snapshot()
        finally:
            r.close()

    def _gov(self, kind, op, args, obo, rid, thunk, token, requester=None):
        with self._lock:
            if self.crashed:
                return thunk()
            if rid and self.anchor is not None and not self.no_anchor and self.anchor.lookup(self.stream, rid):
                return CallResult("OK", {"replayed": True})
            _, pre = self._rows(0)
            head = pre.get("log_head", 0)
            tick, doc_pre = self.clock.now(), self._auth_doc()
            res = thunk()
            sub = self._sub(token)
            why = res.body.get("why") or res.body.get("reason") or "ok"
            gov = res.status in GOV and sub is not None and why not in ("no", "schema", "token") and \
                (res.status != "INVALID" or kind in ("delegate", "revoke")
                 or str(why).startswith(("precondition", "approval_required")))
            if not gov:
                return res
            rows, _ = self._rows(head)
            rows = [r for r in rows if r["seq"] > head]
            return self._envelope(kind, sub, op, args, obo, rid, requester, res, why, pre, doc_pre, rows, head, tick)

    def _envelope(self, kind, sub, op, args, obo, rid, requester, res, why, pre, doc_pre, rows, head, tick):
        commit = next((r for r in rows if r["kind"] == "mark" and r["ref"] == "commit"), None)
        eff = rows if (res.status == "OK" and rows) else []
        post = self._auth_doc()
        use = post if (kind in ("delegate", "revoke") and res.status == "OK") else doc_pre
        gop = op if kind in ("call_tool", "direct", "approve") else None
        blobs = pv.artifact_blobs(kind, gop, args if gop else None, self.ops, pre, use)
        head_e = None if (self.no_anchor or self.anchor is None) else self.anchor.head(self.stream)
        seq = (head_e["seq"] + 1) if head_e else (len(self.history.keys("env/")) + 1)
        prev = head_e["root"] if head_e else pv.ZERO
        did = rid or f"appr-{seq}"
        dec = {"decision_id": did, "kind": kind, "subject": sub, "on_behalf_of": obo, "operation": gop,
               "args_digest": pv.args_digest(args), "status": res.status, "reason": str(why)[:40],
               "effect_digest": pv.effect_digest(eff), "world_seq": commit["seq"] if commit else (
                   eff[-1]["seq"] if eff else head), "tick": commit["tick"] if commit else tick, "authority_path": []}
        arts = pv.expected_artifacts(blobs)
        for ks in blobs.values():
            for b in ks:
                self.history.put("art/" + _sha(b), b)
        for b in blobs["evidence"]:
            self.history.put("refs/" + _sha(b), json.loads(b)["ref"].encode())
        env = pv.make_envelope(self.stream, seq, prev, dec, arts)
        rec = {"envelope": env}
        if "digest_omission" in self.mutants:
            env["artifacts"] = {k: v for k, v in arts.items() if k != "policy"}
            rec["policy_digest"] = arts["policy"]
        root = pv.root_of(env)
        try:
            if self.no_anchor or self.anchor is None:
                receipt = {"stream": self.stream, "seq": seq, "decision_id": did, "root": root,
                           "prev_entry": prev, "i": seq - 1, "mac": "self-signed"}
            else:
                receipt = self.anchor.append(self.stream, seq, did, root)
        except AnchorError:
            return CallResult("UNAVAILABLE", {"reason": "anchor_unavailable"})
        self.history.put(f"env/{seq:08d}", pv.canon(rec))
        self.history.put(f"rcpt/{seq:08d}", pv.canon(receipt))
        if kind == "approve" and res.status == "OK":
            self.history.put(f"appr/{did}", pv.canon({"approve_decision": did, "requester": requester, "obo": obo,
                                                       "operation": op, "args": args}))
        return res


class FakeH27Variant:
    audience = "fake"
    TEST_WORLD_WRITER = "fake-service"
    HISTORY_LAYOUT = {"approval": "appr/", "idempotency": "idem/", "envelope": "env/", "artifact": "art/",
                      "receipt": "rcpt/"}

    def __init__(self, mutants=(), paranoid=False, no_anchor=False, name="fake-honest"):
        self.mutants, self.paranoid, self.no_anchor, self.name = mutants_mod.validate(mutants), paranoid, no_anchor, name

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None):
        return HonestDep("correct", domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants, history, anchor,
                         self.paranoid, self.no_anchor)


def load(name, mutants=()):
    """fake-h27-honest | fake-h27-paranoid | fake-h27-noanchor | fake-h27-<mutant>"""
    tail = name.split("fake-h27-", 1)[1]
    if tail == "honest":
        return FakeH27Variant(mutants, name=name)
    if tail == "paranoid":
        return FakeH27Variant(mutants, paranoid=True, name=name)
    if tail == "noanchor":
        return FakeH27Variant(mutants, no_anchor=True, name=name)
    return FakeH27Variant(tuple(mutants) + (tail,), name=name)
