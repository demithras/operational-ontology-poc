"""A finished base history + the oracle's expected bindings, written BEFORE any tampering (B1), and the independent
root check against the ANCHOR (not the HistoryStore): divergences are `binding_divergence`, a missing anchor entry for
an OK decision is `unanchored_ack` (R27-6)."""
from __future__ import annotations

import copy
import os
import shutil
from dataclasses import dataclass, field

from r3_oracle import provenance as pv
from r3_shared.anchor import AnchorError

from . import layout
from .stream import Stream, copy_db


@dataclass
class Base:
    id: str
    domain: str
    stream: Stream
    stream_id: str
    sc: layout.Scan
    decisions: list[dict]            # harness records with expected bindings; decision["ids"] filled
    ids: dict[int, str]              # seq -> decision id (variant's, from the envelope; harness's for non-approve)
    bundles: list[dict] = field(default_factory=list)
    divergences: list[dict] = field(default_factory=list)
    unanchored: list[dict] = field(default_factory=list)
    tags: set = field(default_factory=set)

    @property
    def n(self) -> int:
        return len(self.decisions)

    def bound(self, seq: int) -> list[tuple[str, str]]:
        a = self.decisions[seq - 1]["artifacts"]
        return [("evidence", d) for d in a["evidence"]] + [(k, a[k]) for k in ("authority", "policy", "contract")]

    def all_digests(self) -> set[str]:
        return {d for s in range(1, self.n + 1) for _, d in self.bound(s)}

    def blob_bytes(self, digest: str) -> bytes | None:
        for d in self.decisions:
            for ks in d["blobs"].values():
                for b in ks:
                    if pv.sha(b) == digest:
                        return b
        return None

    def deploy_auth(self) -> dict:
        a = copy.deepcopy(self.stream.auth)
        if self.stream.v2:
            a = {**a, "capabilities": [], "revoked": []}
        return a

    def copy_to(self, dst: str) -> tuple[str, str]:
        os.makedirs(dst, exist_ok=True)
        w, h = os.path.join(dst, "world.db"), os.path.join(dst, "hist.db")
        copy_db(self.stream.world_path, w)
        copy_db(self.stream.hist_path, h)
        return w, h


def analyze(stream: Stream, anchor, base_id: str) -> Base:
    sc = layout.scan(stream.view)
    first = sc.envs.get(1)
    stream_id = first[0]["env"]["stream"] if first else "?"
    b = Base(base_id, stream.domain, stream, stream_id, sc, stream.decisions, {})
    prev_oracle = pv.ZERO
    for rec in stream.decisions:
        seq = rec["seq"]
        env = sc.env(seq)
        row = {"base": base_id, "seq": seq, "kind": rec["kind"], "status": rec["status"], "expected": {
            "decision": rec["decision"], "artifacts": rec["artifacts"]}, "variant_envelope": env}
        div = []
        if env is None:
            div.append("missing_envelope")
            b.ids[seq] = rec["decision"]["decision_id"] or f"?{seq}"
        else:
            b.ids[seq] = env["decision"].get("decision_id")
            exp_dec = dict(rec["decision"])
            if exp_dec["decision_id"] is None:  # approve(): the protocol gives no request_id; the variant names it
                exp_dec["decision_id"] = b.ids[seq]
            rec["decision"] = exp_dec
            div += pv.compare_binding({"decision": exp_dec, "artifacts": rec["artifacts"]}, env)
            if env.get("stream") != stream_id or env.get("seq") != seq:
                div.append("stream_or_seq")
        try:
            a = anchor.get(stream_id, seq)
        except AnchorError:
            a = None
        row["anchored_root"] = a["root"] if a else None
        if env is not None:
            full = {**rec["decision"], "reason": env["decision"].get("reason"),
                    "authority_path": env["decision"].get("authority_path")}
            oracle_env = pv.make_envelope(stream_id, seq, prev_oracle, full, rec["artifacts"])
            row["oracle_root"], prev_oracle = pv.root_of(oracle_env), pv.root_of(oracle_env)
            row["stored_root"] = pv.root_of(env)
            if a and a["root"] != row["oracle_root"]:
                div.append("root")
            if a and a["root"] != row["stored_root"]:
                div.append("stored_root_not_anchored")
        if a is None and rec["status"] == "OK" and rec["rows"]:
            b.unanchored.append({"base": base_id, "seq": seq, "decision": b.ids[seq]})
        if rec.get("authority_ok") is False:
            div.append("authority_version")
        row["divergences"] = div
        if div:
            b.divergences.append({"base": base_id, "seq": seq, "diffs": div})
        b.bundles.append(row)
    stream.release()
    return b


def cleanup(stream: Stream) -> None:
    shutil.rmtree(stream.root, ignore_errors=True)
