"""Replay/explain for the H27 fakes: PROT-H27 s6 against the anchor; mutants and modes weaken one check each."""
from __future__ import annotations

import hashlib
import json

from r3_oracle import authority, ops_model, provenance as pv
from r3_shared.anchor import AnchorError
from r3_shared.variant import ReplayResult


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _parse(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


class ReplayMixin:
    def _envs(self) -> dict[int, dict]:
        """seq -> {"key", "rec", "env"} for every stored envelope record that parses."""
        out = {}
        for k in self.history.keys("env/"):
            rec = _parse(self.history.get(k))
            env = rec.get("envelope") if isinstance(rec, dict) else None
            if isinstance(env, dict) and isinstance(env.get("seq"), int):
                out[env["seq"]] = {"key": k, "rec": rec, "env": env}
        return out

    def _verified(self) -> list[dict]:
        """Decision scalars of envelopes whose root matches the anchor (used for approvals / continuation)."""
        if self.anchor is None or self.no_anchor:
            return []
        out = []
        for seq, e in self._envs().items():
            a = self.anchor.get(self.stream, seq)
            if a and a["root"] == pv.root_of(e["env"]) and a["decision_id"] == e["env"]["decision"].get("decision_id"):
                out.append(e["env"]["decision"])
        return out

    def replay(self, decision_id):
        if self.paranoid:
            return ReplayResult("TAMPERED", "paranoid")
        if self.history is None or self.anchor is None:
            return ReplayResult("UNRESOLVED", "no_anchor", None, {})
        envs = self._envs()
        target = next((e for e in envs.values() if e["env"].get("decision", {}).get("decision_id") == decision_id), None)
        if target is None:
            a = self._anchor_lookup(decision_id)
            return ReplayResult("UNRESOLVED", "missing_envelope" if a else "unknown_decision")
        n = target["env"]["seq"]
        for m in range(n, 0, -1):
            e = envs.get(m)
            if e is None:
                return ReplayResult("UNRESOLVED", "missing_envelope")
            root = pv.root_of(e["env"])
            ref = self._root_of_record(m)
            if ref is None:
                return ReplayResult("UNRESOLVED", "missing_anchor_entry")
            ref_root, ref_dec = ref
            if root != ref_root or (m == n and ref_dec != decision_id):
                return ReplayResult("TAMPERED", f"root_mismatch_at_{m}")
            if m > 1:
                prev_ref = self._root_of_record(m - 1)
                if prev_ref is None:
                    return ReplayResult("UNRESOLVED", "missing_anchor_entry")
                if e["env"]["prev"] != prev_ref[0]:
                    return ReplayResult("TAMPERED", f"prev_mismatch_at_{m}")
            elif e["env"]["prev"] != pv.ZERO:
                return ReplayResult("TAMPERED", "prev_mismatch_at_1")
        return self._check_artifacts(target)

    def explain(self, decision_id):
        return self.replay(decision_id)

    def _anchor_lookup(self, decision_id):
        try:
            return self.anchor.lookup(self.stream, decision_id)
        except AnchorError:
            return None

    def _root_of_record(self, m):
        if "receipt_self_trust" in self.mutants:  # the weakened check: the stored copy of the receipt
            r = _parse(self.history.get(f"rcpt/{m:08d}"))
            return (r["root"], r["decision_id"]) if isinstance(r, dict) and "root" in r else None
        try:
            a = self.anchor.get(self.stream, m)
        except AnchorError:
            return None
        return (a["root"], a["decision_id"]) if a else None

    def _check_artifacts(self, target):
        env, rec = target["env"], target["rec"]
        arts = dict(env["artifacts"])
        if "digest_omission" in self.mutants:
            arts["policy"] = rec.get("policy_digest")
        got = {}
        for kind, ds in [("evidence", arts.get("evidence", []))] + [(k, [arts.get(k)]) for k in ("authority", "policy", "contract")]:
            for d in ds:
                b = None if d is None else self.history.get("art/" + d)
                if "evidence_rebinding" in self.mutants and kind == "evidence":
                    b = self._latest_by_ref(env, d, b)
                if b is None and "fallback_to_current" in self.mutants and kind != "evidence":
                    b = self._current(kind, env)
                    if b is not None and _sha(b) != d:
                        b = None
                if b is None:
                    return ReplayResult("UNRESOLVED", "missing_artifact")
                if _sha(b) != d and not ("evidence_rebinding" in self.mutants and kind == "evidence"):
                    return ReplayResult("TAMPERED", "artifact_digest_mismatch")
                got[_sha(b)] = b
        if not self._authority_recheck(env, got):
            return ReplayResult("TAMPERED", "authority_decision_changed")
        return ReplayResult("VERIFIED", "ok", env, got)

    def _latest_by_ref(self, env, d, b):
        """MUTANT evidence_rebinding: resolve evidence by ref (latest stored version), not by the bound digest."""
        ref = (self.history.get("refs/" + d) or b"").decode()
        best = None
        for k in self.history.keys("art/"):
            x = _parse(self.history.get(k))
            if isinstance(x, dict) and x.get("ref") == ref and "version" in x:
                if best is None or x["version"] > best[0]:
                    best = (x["version"], self.history.get(k))
        return best[1] if best else b

    def _current(self, kind, env):
        """MUTANT fallback_to_current: the CURRENT authority/policy/contract content."""
        op = env["decision"].get("operation")
        if kind == "authority":
            return pv.authority_artifact(self._auth_doc())
        if op is None:
            return pv.NULL_BYTES
        return pv.policy_artifact(self.ops, op) if kind == "policy" else pv.contract_artifact(self.ops, op)

    def _authority_recheck(self, env, got) -> bool:
        d, a = env["decision"], env["artifacts"]
        if d["kind"] not in ("call_tool", "direct") or d["status"] != "OK":
            return True
        doc, con = _parse(got.get(a["authority"], b"")), _parse(got.get(a["contract"], b""))
        if doc is None or con is None:
            return True
        types = {i["resource_type"] for i in con["inputs"] if i["type"] == "resource"}
        res = []
        for dg in a["evidence"]:
            e = _parse(got.get(dg, b""))
            if e and e["ref"].split(":", 1)[0] in types:
                res.append(tuple(e["ref"].split(":", 1)))
        return authority.decide(d["subject"], d["on_behalf_of"], d["operation"], res, doc).allow
