"""Replay and explanation (PROT-H27 s6). Runs on a FRESH deployment (empty state_dir) over the same world store and
HistoryStore; the ONLY trusted input is the anchor. Artifacts are resolved strictly by their bound digest: a missing one is
UNRESOLVED `missing_artifact` - never replaced by the current spec or the current world (R27-2).
"""
from __future__ import annotations

import json

from r3_shared.anchor import AnchorError
from r3_shared.evidence import canonical_bytes
from r3_shared.variant import ReplayResult

from .histledger import commit_mark
from .pdp import Pdp
from .provenance import ZERO, sha

AUTH_DENY = {"no_matching_allow", "no_matching_allow_or_denied", "on_behalf_of_not_delegator", "unknown_principal",
             "unknown_delegator", "no_delegation", "denied_by_deny_grant", "no_delegable_grant",
             "delegator_not_allowed", "no_valid_path"}
ENV_KEYS = {"v", "stream", "seq", "prev", "decision", "artifacts"}
ART_KEYS = {"evidence", "authority", "policy", "contract"}


class _Stop(Exception):
    def __init__(self, status: str, reason: str):
        self.result = ReplayResult(status, reason)


class Replayer:
    def __init__(self, svc):
        self.s = svc
        self._anchor_cache: dict[int, dict] = {}  # anchor entries are immutable once appended

    def _entry(self, seq: int):
        if "receipt_self_trust" in self.s.mutants:  # BUG: trusts the receipt copy kept in the mutable HistoryStore
            raw = self.s.history.get(f"receipt/{seq:010d}")
            return json.loads(raw) if raw else None
        if seq not in self._anchor_cache:
            e = self.s.anchor.get(self.s.stream, seq)
            if e is not None:
                self._anchor_cache[seq] = e
            return e
        return self._anchor_cache[seq]

    def replay(self, rid: str) -> ReplayResult:
        s = self.s
        if s.history is None or s.anchor is None:
            return ReplayResult("UNRESOLVED", "no_anchor")
        try:
            return self._replay(rid)
        except _Stop as st:
            return st.result
        except AnchorError:
            return ReplayResult("UNRESOLVED", "anchor_unavailable")
        except (ValueError, KeyError, TypeError):
            return ReplayResult("TAMPERED", "malformed_history")

    def _find(self, rid: str) -> int:
        s = self.s
        if "receipt_self_trust" in s.mutants:
            for k in s.history.keys("receipt/"):
                r = json.loads(s.history.get(k))
                if r.get("decision_id") == rid:
                    return r["seq"]
        else:
            a = s.anchor.lookup(s.stream, rid)
            if a is not None:
                self._anchor_cache[a["seq"]] = a
                return a["seq"]
        h = s.factory("conventional-service")
        try:
            committed = commit_mark(h, rid) is not None
        finally:
            h.close()
        raise _Stop("UNRESOLVED", "unanchored" if committed else "unknown_decision")

    def _replay(self, rid: str) -> ReplayResult:
        s, n = self.s, self._find(rid)
        env = None
        for m in range(n, 0, -1):
            raw = s.history.get(f"env/{m:010d}")
            if raw is None:
                raise _Stop("UNRESOLVED", "missing_envelope")
            a = self._entry(m)
            if a is None:
                raise _Stop("UNRESOLVED", "missing_anchor_entry")
            if sha(raw) != a["root"]:
                raise _Stop("TAMPERED", f"root_mismatch_at_{m}")
            e = json.loads(raw)
            if not isinstance(e, dict) or set(e) != ENV_KEYS or canonical_bytes(e) != raw or e["seq"] != m \
                    or e["stream"] != s.stream:
                raise _Stop("TAMPERED", f"malformed_envelope_at_{m}")
            prev = self._entry(m - 1)["root"] if m > 1 else ZERO
            if m > 1 and self._entry(m - 1) is None:
                raise _Stop("UNRESOLVED", "missing_anchor_entry")
            if e["prev"] != prev:
                raise _Stop("TAMPERED", f"prev_mismatch_at_{m}")
            if m == n:
                env = e
                if a["decision_id"] != rid or e["decision"]["decision_id"] != rid:
                    raise _Stop("TAMPERED", "decision_id_mismatch")
        arts = self._artifacts(env, n)
        self._authority_check(env, arts)
        return ReplayResult("VERIFIED", "ok", env, {d: b for d, b in arts["bytes"].items()})

    def _blob(self, digest: str, kind: str, operation: str = "") -> bytes:
        s = self.s
        b = s.history.get(f"art/{digest}")
        if b is None and "fallback_to_current" in s.mutants:  # BUG: substitutes the current spec when the history lacks it
            b = s.current_artifact(kind, operation)
            b = b if b is not None and sha(b) == digest else None
        if b is None:
            raise _Stop("UNRESOLVED", "missing_artifact")
        if "evidence_rebinding" in s.mutants and kind == "evidence":  # BUG: resolves evidence by ref, latest stored version
            latest = s.history.get("evref/" + json.loads(b)["ref"])
            return s.history.get(f"art/{latest.decode()}") if latest else b
        if sha(b) != digest:
            raise _Stop("TAMPERED", "artifact_digest_mismatch")
        return b

    def _artifacts(self, env: dict, n: int) -> dict:
        a = env["artifacts"]
        if "digest_omission" in self.s.mutants and "policy" not in a:
            side = self.s.history.get(f"side/{n:010d}")
            a = {**a, "policy": (side or b"").decode()}
        if set(a) != ART_KEYS or not isinstance(a["evidence"], list) or a["evidence"] != sorted(a["evidence"]):
            raise _Stop("TAMPERED", "malformed_artifact_bindings")
        out: dict = {"bytes": {}, "evidence": []}
        for kind in ("authority", "policy", "contract"):
            out[kind] = self._blob(a[kind], kind, env["decision"]["operation"])
            out["bytes"][a[kind]] = out[kind]
        for d in a["evidence"]:
            b = self._blob(d, "evidence")
            out["evidence"].append(json.loads(b))
            out["bytes"][d] = b
        return out

    def _authority_check(self, env: dict, arts: dict) -> None:
        """Re-evaluate the AUTHORITY decision over the bound authority artifact (PROT-H23 rule / PROT-H24 s3)."""
        d = env["decision"]
        if d["kind"] not in ("call_tool", "direct"):
            return
        contract = json.loads(arts["contract"])
        types = {i["resource_type"] for i in contract["inputs"] if i["type"] == "resource"}
        res = [tuple(e["ref"].split(":", 1)) for e in arts["evidence"] if e["ref"].split(":", 1)[0] in types]
        got = Pdp(json.loads(arts["authority"]), 1).decide(d["subject"], d["on_behalf_of"], d["operation"], res, d["tick"])
        recorded_allow = not (d["status"] == "DENIED" and d["reason"] in AUTH_DENY)
        if got.allowed != recorded_allow:
            raise _Stop("TAMPERED", "authority_decision_mismatch")
