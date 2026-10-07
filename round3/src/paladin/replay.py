"""Replay / explain (PROT-H27 s6) on a FRESH deployment: everything is read from the HistoryStore and the anchor service;
nothing from process memory. VERIFIED only if the envelope, its anchored root, the whole prev chain, every bound artifact
digest and the recorded authority verdict all hold; otherwise TAMPERED (positive mismatch) or UNRESOLVED (something missing).
Mutants (frozen names) sit at the lines where the real bug would live: fallback_to_current, evidence_rebinding,
receipt_self_trust, and digest_omission (replay side of the sidecar digest)."""
from __future__ import annotations

import json
from typing import Any

from paladin import evid
from paladin.authreplay import AUTH_DENY
from paladin.prov import ART, DECISION_KEYS, ENV, REF, RCPT, SIDE
from r3_shared.anchor import ZERO, AnchorError
from r3_shared.evidence import canonical_bytes
from r3_shared.variant import ReplayResult

ENV_KEYS = {"v", "stream", "seq", "prev", "decision", "artifacts"}
ART_KEYS = {"evidence", "authority", "policy", "contract"}


def _bad(status: str, reason: str) -> ReplayResult:
    return ReplayResult(status, reason, None, {})


def _parse(raw: bytes | None) -> dict | None:
    try:
        e = json.loads(raw) if raw is not None else None
    except ValueError:
        return None
    return e if isinstance(e, dict) else None


def locate(h, anchor, stream: str, decision_id: str) -> tuple[bytes | None, dict | None, str | None]:
    """The stored envelope of the decision (by its anchored seq, else by content), the anchor's lookup entry and its store key."""
    a = anchor.lookup(stream, decision_id)
    if a is not None:
        raw = h.get(f"{ENV}{a['seq']:08d}")
        e = _parse(raw)
        if e is not None and e.get("decision", {}).get("decision_id") == decision_id:
            return raw, a, f"{ENV}{a['seq']:08d}"
    for k in h.keys(ENV):  # moved / renamed envelope: found by content
        raw = h.get(k)
        e = _parse(raw)
        if e is not None and isinstance(e.get("decision"), dict) and e["decision"].get("decision_id") == decision_id:
            return raw, a, k
    return None, a, None


def replay(dep, decision_id: str) -> ReplayResult:
    """`dep`: the deployment (history, anchor, stream, mutants, reauth, current-spec accessors)."""
    h, anchor, stream, mut = dep.history, dep.anchor, dep.stream, dep.mutants
    if h is None or anchor is None:
        return _bad("UNRESOLVED", "no_anchor")
    try:
        raw, a, key = locate(h, anchor, stream, decision_id)
        if raw is None:
            return _bad("UNRESOLVED", "missing_envelope" if a is not None else "unknown_decision")
        env = _parse(raw)
        if set(env) != ENV_KEYS or env["stream"] != stream or not isinstance(env["decision"], dict) \
                or set(env["decision"]) != set(DECISION_KEYS) or not isinstance(env["artifacts"], dict):
            return _bad("TAMPERED", "envelope_shape")
        n = env["seq"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            return _bad("TAMPERED", "envelope_seq")
        if key != f"{ENV}{n:08d}":  # an envelope stored away from its own position was moved / reordered
            return _bad("TAMPERED", "envelope_misplaced")
        roots: dict[int, str] = {}

        def anchored(m: int) -> dict | None:
            if m not in roots:
                if "receipt_self_trust" in mut:  # MUTANT: trust the receipt copy kept in the HistoryStore
                    r = _parse(h.get(f"{RCPT}{m:08d}"))
                    roots[m] = r
                else:
                    roots[m] = anchor.get(stream, m)
            return roots[m]

        for m in range(n, 0, -1):
            am = anchored(m)
            if am is None:
                return _bad("UNRESOLVED", "unanchored" if m == n else "missing_anchor_entry")
            rm = raw if m == n else h.get(f"{ENV}{m:08d}")
            if rm is None:
                return _bad("UNRESOLVED", "missing_envelope")
            if evid.digest(rm) != am["root"] or (m == n and am["decision_id"] != decision_id):
                return _bad("TAMPERED", f"root_mismatch_at_{m}")
            em = env if m == n else _parse(rm)
            if em is None or not isinstance(em.get("prev"), str) or em.get("seq") != m:
                return _bad("TAMPERED", f"envelope_unparseable_at_{m}")
            want = ZERO if m == 1 else (anchored(m - 1) or {}).get("root")
            if want is None or em["prev"] != want:
                return _bad("TAMPERED", f"prev_mismatch_at_{m}")
        arts_d = dict(env["artifacts"])
        if "digest_omission" in mut and "policy" not in arts_d:
            side = _parse(h.get(f"{SIDE}{n:08d}")) or {}
            if "policy" in side:
                arts_d["policy"] = side["policy"]
        if set(arts_d) != ART_KEYS or not isinstance(arts_d["evidence"], list):
            return _bad("TAMPERED", "artifact_binding_shape")
        blobs: dict[str, bytes] = {}
        for kind in ("authority", "policy", "contract"):
            b = _artifact(dep, kind, arts_d[kind], h, env["decision"]["operation"])
            if isinstance(b, ReplayResult):
                return b
            blobs[arts_d[kind]] = b
        for d in arts_d["evidence"]:
            b = _artifact(dep, "evidence", d, h, None)
            if isinstance(b, ReplayResult):
                return b
            blobs[d] = b
        bad = _reauthorize(dep, env["decision"], arts_d, blobs)
        if bad is not None:
            return _bad("TAMPERED", bad)
        return ReplayResult("VERIFIED", "ok", env, blobs)
    except AnchorError:
        return _bad("UNRESOLVED", "anchor_unavailable")
    except (KeyError, TypeError, ValueError, AttributeError):
        return _bad("TAMPERED", "malformed_history")


def _artifact(dep, kind: str, d: Any, h, op: Any = None) -> bytes | ReplayResult:
    if not isinstance(d, str):
        return _bad("TAMPERED", "artifact_binding_shape")
    b = h.get(ART + d)
    if "evidence_rebinding" in dep.mutants and kind == "evidence":
        # MUTANT: resolve evidence by its ref (the latest stored version), not by the bound digest
        ref = _ref_of(h, d)
        cur = h.get(REF + ref) if ref is not None else None
        if cur is not None:
            return cur
    if b is None:
        if "fallback_to_current" in dep.mutants and kind != "evidence":  # MUTANT: current spec instead of the bound artifact
            return dep.current_artifact(kind, op)
        return _bad("UNRESOLVED", "missing_artifact")
    if evid.digest(b) != d:
        return _bad("TAMPERED", "artifact_digest_mismatch")
    return b


def _ref_of(h, digest: str) -> str | None:
    b = h.get(ART + digest)
    return json.loads(b).get("ref") if b is not None else None


def _reauthorize(dep, dec: dict, arts_d: dict, blobs: dict) -> str | None:
    if dec["kind"] not in ("call_tool", "direct"):
        return None
    doc = json.loads(blobs[arts_d["authority"]])
    spec = next((o for o in dep.ops_spec["operations"] if o["name"] == dec["operation"]), None)
    if spec is None:
        return "unknown_operation"
    intypes = {i["resource_type"] for i in spec["inputs"] if i["type"] == "resource"}  # `newest` evidence is not a request resource
    refs = [e["ref"] for e in (json.loads(blobs[d]) for d in arts_d["evidence"])
            if not e.get("absent") and e["ref"].split(":", 1)[0] in intypes]
    want = dec["reason"] not in AUTH_DENY
    got = dep.reauth.allowed(doc, dec["subject"], dec["on_behalf_of"], dec["operation"], refs, dec["tick"],
                             dec["authority_path"])
    return None if got == want else "authority_verdict_mismatch"
