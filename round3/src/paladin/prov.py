"""Decision provenance (PROT-H27 s1-s3): artifacts content-addressed in the HistoryStore, an envelope chained per stream,
its root appended to the anchor service BEFORE the decision's result is returned (anchor-before-ack, R27-6).

The Engine's own ProvenanceEnvelope (engine/provenance.py, per-effect, rendered into the external system) is unchanged; this is
the per-DECISION envelope of PROT-H27 s2, composed by the Paladin control plane in `Prov.record`, never by an adapter.
HistoryStore keys (HISTORY_LAYOUT): env/<seq> art/<digest> rcpt/<seq> ref/<T:k> side/<seq> meta/stream.
"""
from __future__ import annotations

import json
import random
from typing import Any

from paladin import evid
from r3_shared.anchor import ZERO, AnchorError
from r3_shared.evidence import canonical_bytes

ENV, ART, RCPT, REF, SIDE, META_STREAM = "env/", "art/", "rcpt/", "ref/", "side/", "meta/stream"
HISTORY_LAYOUT = {"envelope": ENV, "artifact": ART, "receipt": RCPT, "evidence_ref_index": REF, "envelope_sidecar": SIDE,
                  "stream": META_STREAM, "approval": "led/appr/", "idempotency": "led/req/", "ledger_meta": "led/meta/"}
DECISION_KEYS = ("decision_id", "kind", "subject", "on_behalf_of", "operation", "args_digest", "status", "reason",
                 "effect_digest", "world_seq", "tick", "authority_path")
_RNG = random.Random(0x7E57)  # seeded: deterministic stream ids per process; uniqueness is re-checked against the anchor


def stream_for(history, anchor, domain: str) -> str:
    raw = history.get(META_STREAM)
    if raw is not None:
        return raw.decode(errors="replace")
    while True:
        s = f"paladin-{domain}-{_RNG.getrandbits(64):016x}"
        try:
            if anchor is None or anchor.head(s) is None:
                break
        except AnchorError:
            break
    history.put(META_STREAM, s.encode())
    return s


class Prov:
    def __init__(self, history, anchor, stream: str, mutants=()):
        self.h, self.a, self.stream, self.mutants = history, anchor, stream, frozenset(mutants)
        self._head: tuple[int, str] | None = None

    def _next(self) -> tuple[int, str]:
        if self._head is None:
            e = self.a.head(self.stream)
            self._head = (e["seq"], e["root"]) if e else (0, ZERO)
        return self._head[0] + 1, self._head[1]

    def decision_scalars(self, d: dict) -> dict:
        return {"decision_id": d["rid"], "kind": d["kind"], "subject": d["sub"], "on_behalf_of": d["obo"],
                "operation": d["op"], "args_digest": evid.digest(canonical_bytes(d["args"])), "status": d["status"],
                "reason": d["reason"], "effect_digest": evid.digest(canonical_bytes(d["rows"])),
                "world_seq": d["world_seq"], "tick": d["tick"], "authority_path": list(d["path"])}

    def record(self, d: dict) -> str | None:
        """Bind, chain and anchor one decision. None on success; an error reason (anchor_unavailable / float_in_artifact)."""
        arts = evid.artifact_set(d["ops_spec"], d["art_op"], d["doc"], d["evidence"])
        if any(evid.has_float(e) for e in d["evidence"]) or evid.has_float(d["doc"]):
            return "float_in_artifact"
        try:
            seq, prev = self._next()
            if d["rid"] is None:  # approve() carries no request id: its decision id is its stream position
                d["rid"] = f"approve:{seq:08d}"
            digs = {k: ([evid.digest(b) for b in v] if k == "evidence" else evid.digest(v)) for k, v in arts.items()}
            for b in arts["evidence"] + [arts["authority"], arts["policy"], arts["contract"]]:
                self.h.put(ART + evid.digest(b), b)
            side = None
            artifacts = {"evidence": sorted(set(digs["evidence"])), "authority": digs["authority"],
                         "policy": digs["policy"], "contract": digs["contract"]}
            if "digest_omission" in self.mutants:  # MUTANT: the policy digest is stored beside the envelope, not under its root
                side, artifacts = {"policy": artifacts.pop("policy")}, artifacts
            env = {"v": 1, "stream": self.stream, "seq": seq, "prev": prev, "decision": self.decision_scalars(d),
                   "artifacts": artifacts}
            raw = canonical_bytes(env)
            root = evid.digest(raw)
            for e in d["evidence"]:  # latest-by-ref index (the lookup an evidence_rebinding replay would wrongly use)
                self.h.put(REF + e["ref"], canonical_bytes(e))
            if side is not None:
                self.h.put(f"{SIDE}{seq:08d}", canonical_bytes(side))
            self.h.put(f"{ENV}{seq:08d}", raw)  # stored BEFORE the append: a decision the anchor never saw replays unresolved
            receipt = self.a.append(self.stream, seq, d["rid"], root)
            self.h.put(f"{RCPT}{seq:08d}", canonical_bytes(receipt))
            self._head = (seq, root)
            return None
        except AnchorError:
            self._head = None
            return "anchor_unavailable"

    def anchored_decision(self, rid: str) -> dict | None:
        """Continuation check (R27-5): the anchor's entry for a decision id, with the stored envelope proven against its root.
        Returns {"status","kind"} of the anchored decision; raises LookupError when it is anchored but not provable."""
        e = self.a.lookup(self.stream, rid)
        if e is None:
            return None
        raw = self.h.get(f"{ENV}{e['seq']:08d}")
        if raw is None or evid.digest(raw) != e["root"]:
            raise LookupError("anchored decision without a provable envelope")
        dec = json.loads(raw)["decision"]
        return {"status": dec["status"], "kind": dec["kind"], "subject": dec["subject"], "operation": dec["operation"],
                "args_digest": dec["args_digest"]}

    def consumed(self, approval_id: str) -> bool:
        return self.a.lookup(self.stream + ".consumed", approval_id) is not None

    def mark_consumed(self, approval_id: str, rid: str) -> None:
        s = self.stream + ".consumed"
        h = self.a.head(s)
        self.a.append(s, (h["seq"] if h else 0) + 1, approval_id, evid.digest(rid.encode()))
