"""Recompute every H24 metric from the RAW rows (authority-sequences.jsonl.gz + revocation-races.json). The runner
writes summaries with this function and the evaluator re-derives them with it: summaries are only cross-checked."""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

SEQ_FILE = "authority-sequences.jsonl.gz"
RACE_FILE = "revocation-races.json"
FILES = ("authority-state-machine.json", "revocation-races.json", "delegation-attenuation.json", "safe-progress.json",
         "mutation-results.json")
EXTRA = ("authority-sequences.jsonl.gz",)
TYPES = ("RV", "RA", "EX", "SA", "DP", "AP", "CR", "UN", "SEQ")


def read_sequences(path: Path):
    with gzip.open(path, "rt") as fh:
        for line in fh:
            yield json.loads(line)


def _pct(xs: list[float], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def analyze(vdir: Path) -> dict:
    cls, case_cls, kinds = Counter(), Counter(), Counter()
    uniq, domains, depth_hist, opcov = set(), set(), Counter(), Counter()
    must = ok = 0
    lat: list[float] = []
    attempts: list[list] = []
    seqs = seqs_d4 = max_depth = 0
    edge_req = edge_req_deep = 0

    def rows(cid, domain, calls):
        nonlocal must, ok, max_depth, edge_req, edge_req_deep
        deep = False
        for r in calls:
            for c in r["classes"]:
                cls[c] += 1
            kinds[r["kind"]] += 1
            if r["kind"] == "request":
                opcov[f"{domain}:{r['op']}"] += 1
            if r["kind"] == "delegate":
                o = r.get("oracle") or {}
                attempts.append([cid, r["n"], r.get("intent"), r.get("depth"), r["status"], bool(r["committed"]),
                                 o.get("verdict"), o.get("reason"), ",".join(r["classes"])])
                if r.get("committed") and r.get("depth"):
                    depth_hist[r["depth"]] += 1
                    max_depth = max(max_depth, r["depth"])
                    deep = deep or r["depth"] >= 4
            if r.get("must"):
                must += 1
                ok += bool(r["committed"])
                if r["committed"] and r.get("lat_ms") is not None:
                    lat.append(r["lat_ms"])
        return deep

    for rec in read_sequences(vdir / SEQ_FILE):
        seqs += 1
        uniq.add(rec["digest"])
        domains.add(rec["domain"])
        seqs_d4 += bool(rows(rec["id"], rec["domain"], rec["calls"]))
        for c in rec["case_classes"]:
            case_cls[c] += 1
            cls[c] += 1
    races = json.loads((vdir / RACE_FILE).read_text())["cases"] if (vdir / RACE_FILE).is_file() else []
    by_type, executed = Counter(), 0
    matched = overlapping = rv_over = rv_eff = rv_rev = 0
    for rec in races:
        by_type[rec["type"]] += 1
        domains.add(rec["domain"])
        uniq.add(rec["digest"])
        rows(rec["id"], rec["domain"], rec["calls"])
        for c in rec["case_classes"]:
            case_cls[c] += 1
            cls[c] += 1
        if rec["executed"]:
            executed += 1
            matched += bool(rec["match"])
            overlapping += bool(rec["overlap"])
            if rec["type"] == "RV" and rec["overlap"]:
                rv_over += 1
                rv_eff += rec["order"] == "effect_first"
                rv_rev += rec["order"] == "revoke_first"
    return {
        "sequences": seqs, "unique_sequences": len(uniq), "class_counts": dict(sorted(cls.items())),
        "case_class_counts": dict(sorted(case_cls.items())), "step_kinds": dict(sorted(kinds.items())),
        "depth_hist": {str(k): v for k, v in sorted(depth_hist.items())}, "max_depth": max_depth,
        "sequences_with_depth_ge4": seqs_d4, "domains": sorted(domains), "op_coverage": dict(sorted(opcov.items())),
        "progress": {"must": must, "committed": ok, "ratio": (ok / must) if must else None},
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "n": len(lat)},
        "races": {"cases": len(races), "executed": executed, "matched": matched, "overlapping": overlapping,
                  "overlap_fraction": (overlapping / executed) if executed else None, "by_type": dict(by_type),
                  "rv_overlapping": rv_over, "rv_effect_first": rv_eff, "rv_revoke_first": rv_rev},
        "attempts": attempts}
