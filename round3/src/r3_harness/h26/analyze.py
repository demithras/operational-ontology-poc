"""Pair verdict rows (noninterference) and aggregate counters for the evaluator. A row never carries raw world data
beyond the canonical observation digests (the evidence file is public)."""
from __future__ import annotations

import hashlib
from collections import Counter

from r3_oracle import lowproj

CHANNEL = {"tools": "tools", "read_object": "read", "list_objects": "read", "list_links": "read", "query": "read",
           "subscribe": "events", "poll": "events", "mutate": "mutating", "delegate": "mutating", "revoke": "mutating",
           "constitutional": "mutating", "prov_decision": "provenance", "prov_object": "provenance",
           "authority_used_as": "authority_used_as"}
CHANNELS = ("tools", "read", "events", "mutating", "provenance", "authority_used_as")
FACT_KINDS = ("E", "F", "L", "D", "C", "G")
LEAK = ("divergence", "existence_leak", "value_exfiltration", "provenance_overdisclosure")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pair_row(pair: dict, runs: list[dict]) -> dict:
    a, b = runs
    kinds = pair["kinds"]
    kind = kinds[0] if len(kinds) == 1 else "M"
    div = []
    for i, (x, y) in enumerate(zip(a["obs"], b["obs"])):
        if x != y:
            m = a["rows"][i]["m"] if i < len(a["rows"]) else "?"
            div.append({"i": i, "m": m, "class": f"divergence:{m}:{kind}"})
    if len(a["obs"]) != len(b["obs"]):
        div.append({"i": min(len(a["obs"]), len(b["obs"])), "m": "length", "class": f"divergence:length:{kind}"})
    first = lowproj.diff(a["obs"], b["obs"])
    tags = Counter()
    for r in runs:
        tags.update(t[2].split(":")[0] if t[2].split(":")[0] in ("false_provenance", "over_redaction", "provenance_overdisclosure")
                    else t[2] for t in r["tags"])
    labels = Counter(l for r in runs for l in r["labels"])
    return {"id": pair["id"], "domain": pair["domain"], "observer": pair["observer"], "kinds": kinds, "aa": pair["aa"],
            "channels": sorted({CHANNEL[x["m"]] for x in a["rows"] if x["m"] in CHANNEL}),
            "hidden_probes": sum(1 for x in pair["plan"] if x["m"] == "read_object"),
            "n_obs": len(a["obs"]), "divergences": div, "first": (first or {}) and {k: first[k] for k in ("index",) if k in first},
            "tags": dict(tags), "labels": dict(labels), "obs_sha": [_sha(b"".join(r["obs"])) for r in runs],
            "witness": {"varied": pair["info"], "observer": pair["observer"]} if div else None,
            "lat": [r["lat"] for r in runs]}


def aggregate(rows: list[dict]) -> dict:
    ab = [r for r in rows if not r["aa"]]
    aa = [r for r in rows if r["aa"]]
    c = Counter()
    for r in ab:
        c["pairs"] += 1
        c["divergent_pairs"] += bool(r["divergences"])
        for d in r["divergences"]:
            c[d["class"]] += 1
        for k, v in r["tags"].items():
            c[k] += v
        for l, v in r["labels"].items():
            c[f"label:{l}"] += v
        c["hidden_probes"] += r["hidden_probes"]
    per_kind = Counter(k for r in ab for k in set(r["kinds"]))
    per_channel = Counter(ch for r in ab for ch in r["channels"])
    return {"counts": dict(c), "pairs_by_kind": {k: per_kind.get(k, 0) for k in FACT_KINDS},
            "pairs_by_channel": {k: per_channel.get(k, 0) for k in CHANNELS},
            "aa_total": len(aa), "aa_divergent": sum(bool(r["divergences"]) for r in aa)}
