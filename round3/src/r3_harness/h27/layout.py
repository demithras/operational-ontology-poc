"""Content-based discovery of history records (PROTOCOL-P1d P1d-5: no credit for obscurity, the layout is not trusted):
envelopes = JSON dicts with exactly the frozen envelope keys, receipts = dicts with exactly the anchor-entry keys,
artifacts = values whose sha256 equals an oracle-expected digest. Works on a TamperView (read-only use here)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from r3_oracle import provenance as pv

HEX64 = re.compile(rb"[0-9a-f]{64}")


@dataclass
class Scan:
    envs: dict[int, list[dict]] = field(default_factory=dict)      # seq -> [{key, path, env, record}]
    receipts: dict[int, list[dict]] = field(default_factory=dict)  # seq -> [{key, path, entry, record}]
    blobs: dict[str, list[str]] = field(default_factory=dict)      # sha256(value) -> [key]
    raw: dict[str, bytes] = field(default_factory=dict)

    def env(self, seq: int) -> dict | None:
        hits = self.envs.get(seq) or []
        return hits[0]["env"] if hits else None

    def holders(self, digest: str) -> list[str]:
        return list(self.blobs.get(digest, []))


def scan(view) -> Scan:
    sc = Scan()
    for k in view.keys(""):
        raw = view.read(k)
        if raw is None:
            continue
        sc.raw[k] = raw
        sc.blobs.setdefault(pv.sha(raw), []).append(k)
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        for path, env in pv.find_nested(rec, pv.is_envelope):
            if isinstance(env.get("seq"), int):
                sc.envs.setdefault(env["seq"], []).append({"key": k, "path": path, "env": env, "record": rec})
        for path, ent in pv.find_nested(rec, pv.is_entry):
            if isinstance(ent.get("seq"), int):
                sc.receipts.setdefault(ent["seq"], []).append({"key": k, "path": path, "entry": ent, "record": rec})
    return sc


def hexset(raw: bytes | None) -> frozenset[bytes]:
    return frozenset(HEX64.findall(raw or b""))


def digests_present(sc: Scan, digests) -> dict[str, bool]:
    return {d: bool(sc.blobs.get(d)) for d in digests}
