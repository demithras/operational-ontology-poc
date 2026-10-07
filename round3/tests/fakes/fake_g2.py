"""Reference behaviour for the Gate 2 Deployment methods (fakes only; no authorization semantics beyond valid tokens +
the PROT-H24 s2/s5 issuance/revocation rules). Mixed into FakeDeployment. Envelope = simplified H27 form (chain + anchor)."""
from __future__ import annotations

import hashlib
import json
import random

from r3_shared.anchor import AnchorError
from r3_shared.authgraph import scope_subset
from r3_shared.evidence import canonical_bytes
from r3_shared.variant import CallResult, ReplayResult

EDGE_KEYS = {"id", "issuer", "child", "parent", "scope", "expires_at", "redelegable", "issued_at"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class G2Mixin:
    def _g2_init(self, history, anchor):
        self.history, self.anchor = history, anchor
        self.g2 = {"edges": [], "revoked": [], "used": {}, "results": {}}
        self.stream = None
        if history is not None:
            raw = history.get("meta/stream")
            if raw is None:
                raw = f"fake-{self.domain}-{random.Random(self.domain).getrandbits(64):016x}".encode()
                history.put("meta/stream", raw)
            self.stream = raw.decode()
            saved = history.get("meta/g2")
            if saved:
                self.g2 = json.loads(saved)
        elif self.state_dir:
            from pathlib import Path
            p = Path(self.state_dir) / "g2.json"
            if p.exists():
                self.g2 = json.loads(p.read_text())

    def _g2_save(self):
        if self.history is not None:
            self.history.put("meta/g2", json.dumps(self.g2, sort_keys=True).encode())
        elif self.state_dir:
            from pathlib import Path
            (Path(self.state_dir) / "g2.json").write_text(json.dumps(self.g2, sort_keys=True))

    def _auth_doc(self):
        return {"edges": self.g2["edges"], "revoked": sorted(self.g2["revoked"])}

    def authority_state(self) -> dict:
        return {"spec": self.auth_spec, **self._auth_doc()}

    def _edge_by_id(self):
        return {e["id"]: e for e in self.g2["edges"]}

    def _path(self, eid):
        by, out = self._edge_by_id(), []
        while eid is not None:
            out.append(by[eid])
            eid = by[eid]["parent"]
        return out[::-1]

    def _valid(self, eid, tick):
        return all(e["id"] not in self.g2["revoked"] and (e["expires_at"] is None or tick < e["expires_at"])
                   for e in self._path(eid))

    # ---- mutating G2 calls --------------------------------------------------------------------------------
    def _g2_mutation(self, token, request_id, kind, check, apply):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self._sub(token)
            if sub is None:
                return CallResult("DENIED", {"reason": "token"})
            if request_id in self.g2["results"]:
                return CallResult("OK", self.g2["results"][request_id])
            tick = self.clock.now()
            bad = check(sub, tick)
            if bad is not None:
                return bad
            armed, self._armed = self._armed, None
            if armed == "before_commit":
                self.crashed = True
                return CallResult("UNKNOWN", {"reason": "crashed"})
            body = apply(sub)
            with self.world.transaction(tag="authority") as tx:
                tx.mark("authority", {"op": kind, **body.pop("_mark")})
                seq = tx.mark("commit", {"request_id": request_id, "kind": kind, "authority_version": self.authority_version()})
            self.g2["results"][request_id] = body
            self._g2_save()
            if armed == "after_commit":
                self.crashed = True
                return CallResult("UNKNOWN", {"reason": "crashed"})
            return self._g2_anchor(request_id, kind, sub, seq, tx.tick, body)

    def delegate(self, token, edge, request_id):
        def check(sub, tick):
            if not isinstance(edge, dict) or set(edge) != EDGE_KEYS:
                return CallResult("INVALID", {"reason": "schema"})
            by = self._edge_by_id()
            if edge["id"] in by:
                return CallResult("INVALID", {"reason": "duplicate_edge"})
            if edge["issuer"] != sub:
                return CallResult("DENIED", {"reason": "not_parent_holder"})
            if edge["issuer"] == edge["child"]:
                return CallResult("INVALID", {"reason": "delegation_cycle"})
            par = by.get(edge["parent"]) if edge["parent"] is not None else None
            if edge["parent"] is not None:
                if par is None:
                    return CallResult("INVALID", {"reason": "unknown_parent"})
                path = self._path(par["id"])
                if edge["child"] in {e["issuer"] for e in path}:
                    return CallResult("INVALID", {"reason": "delegation_cycle"})
                if par["child"] != sub:
                    return CallResult("DENIED", {"reason": "not_parent_holder"})
                if not self._valid(par["id"], tick):
                    return CallResult("DENIED", {"reason": "parent_invalid"})
                if not par["redelegable"]:
                    return CallResult("DENIED", {"reason": "not_redelegable"})
                if not scope_subset(edge["scope"], par["scope"]):
                    return CallResult("DENIED", {"reason": "scope_amplification"})
                pe = par["expires_at"]
                if pe is not None and (edge["expires_at"] is None or edge["expires_at"] > pe):
                    return CallResult("DENIED", {"reason": "expiry_amplification"})
            if edge["expires_at"] is not None and edge["expires_at"] <= tick:
                return CallResult("INVALID", {"reason": "already_expired"})
            return None

        def apply(sub):
            self.g2["edges"].append(edge)
            return {"edge_id": edge["id"], "_mark": {"edge": edge, "version": _sha(canonical_bytes(self._auth_doc()))}}
        return self._g2_mutation(token, request_id, "delegate", check, apply)

    def revoke(self, token, edge_id, request_id):
        def check(sub, tick):
            by = self._edge_by_id()
            if edge_id not in by:
                return CallResult("INVALID", {"reason": "unknown_edge"})
            if sub not in {e["issuer"] for e in self._path(edge_id)}:
                return CallResult("DENIED", {"reason": "not_revoker"})
            return None

        def apply(sub):
            if edge_id in self.g2["revoked"]:
                return {"already": True, "_mark": {"edge_id": edge_id, "version": "noop"}}
            self.g2["revoked"].append(edge_id)
            return {"_mark": {"edge_id": edge_id, "version": _sha(canonical_bytes(self._auth_doc()))}}
        return self._g2_mutation(token, request_id, "revoke", check, apply)

    def authority_used(self, request_id):
        rec = self.g2["used"].get(request_id)
        return CallResult("OK", rec) if rec else CallResult("INVALID", {"reason": "unknown_request"})

    # ---- provenance (simplified H27) ----------------------------------------------------------------------
    def _g2_anchor(self, request_id, kind, sub, seq, tick, body):
        if self.history is None or self.anchor is None:
            return CallResult("OK", body)
        art = canonical_bytes({"authority": self._auth_doc()})
        self.history.put(f"art/{_sha(art)}", art)
        n = len(self.history.keys("env/")) + 1
        prev = _sha(self.history.get(f"env/{n - 1:08d}")) if n > 1 else "0" * 64
        env = {"v": 1, "stream": self.stream, "seq": n, "prev": prev,
               "decision": {"decision_id": request_id, "kind": kind, "subject": sub, "world_seq": seq, "tick": tick},
               "artifacts": {"authority": _sha(art)}}
        raw = canonical_bytes(env)
        try:
            self.anchor.append(self.stream, n, request_id, _sha(raw))
        except AnchorError:
            return CallResult("UNAVAILABLE", {"reason": "anchor_unavailable"})
        self.history.put(f"env/{n:08d}", raw)
        return CallResult("OK", body)

    def replay(self, decision_id):
        if self.history is None or self.anchor is None:
            return ReplayResult("UNRESOLVED", "no_anchor", None, {})
        for k in self.history.keys("env/"):
            try:
                env = json.loads(self.history.get(k))
            except ValueError:
                return ReplayResult("TAMPERED", "envelope_unparseable")
            if env.get("decision", {}).get("decision_id") == decision_id:
                break
        else:
            a = self.anchor.lookup(self.stream, decision_id)
            return ReplayResult("UNRESOLVED", "missing_envelope" if a else "unknown_decision")
        n = env["seq"]
        try:
            for m in range(n, 0, -1):  # every root back to seq 1 against the anchor
                raw = self.history.get(f"env/{m:08d}")
                a = self.anchor.get(self.stream, m)
                if raw is None or a is None:
                    return ReplayResult("UNRESOLVED", "missing_envelope" if raw is None else "missing_anchor_entry")
                if _sha(raw) != a["root"] or (m == n and a["decision_id"] != decision_id):
                    return ReplayResult("TAMPERED", f"root_mismatch_at_{m}")
                if m > 1 and json.loads(raw)["prev"] != self.anchor.get(self.stream, m - 1)["root"]:
                    return ReplayResult("TAMPERED", f"prev_mismatch_at_{m}")
        except AnchorError:
            return ReplayResult("UNRESOLVED", "anchor_unavailable")
        arts = {}
        for d in env["artifacts"].values():
            b = self.history.get(f"art/{d}")
            if b is None:
                return ReplayResult("UNRESOLVED", "missing_artifact")
            if _sha(b) != d:
                return ReplayResult("TAMPERED", "artifact_digest_mismatch")
            arts[d] = b
        return ReplayResult("VERIFIED", "ok", env, arts)

    def explain(self, decision_id):
        return self.replay(decision_id)
