"""Recompute every H27 metric from the RAW case records (the evaluator never trusts summaries)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import tamper

ACCEPT = ("tamper_accepted", "rebinding_accepted", "fallback_to_current", "continuation_effect", "unanchored_ack")


def _p(xs: list[float], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def analyze(vdir: Path) -> dict:
    t = json.loads((vdir / "tamper-mutation-results.json").read_text())
    h = json.loads((vdir / "historical-replay.json").read_text())
    cases, controls = t["cases"], h["controls"]
    cc: Counter = Counter()
    unsupported = errors = 0
    d_total = d_detected = d_explain_bad = 0
    applied_classes: Counter = Counter()
    tampered = compound = 0
    bases, base_domain = set(), {}
    lat = []
    for c in cases:
        for k in c["classes_hit"]:
            cc[k] += 1
        for r in c["replays"]:
            unsupported += "unsupported" in r["classes"] or bool(r.get("error") and str(r["error"]).startswith("unsupported"))
            errors += r["replay"] is None and not str(r.get("error") or "").startswith("unsupported") and bool(r.get("error"))
            if r["set"] == "definite":
                d_total += 1
                d_detected += (r["replay"] or {}).get("status", "VERIFIED") != "VERIFIED" if r["replay"] else 1
        if c["applied"]:
            tampered += 1 if (c["definite"] or "continuation" in c["flags"]) else 0
            for a in c["applied"]:
                applied_classes[a] += 1
            compound += 1 if len(c["classes"]) > 1 and len(c["applied"]) > 1 else 0
        bases.add(c["base"])
        base_domain[c["base"]] = c["domain"]
        if c["replays"] and c.get("replay_ms") is not None:
            lat.append(c["replay_ms"] / len(c["replays"]))
    clean_replays = clean_ok = 0
    clean_cc: Counter = Counter()
    for c in controls:
        for r in c["replays"]:
            clean_replays += 1
            clean_ok += not r["classes"] and (r["replay"] or {}).get("status") == "VERIFIED"
            unsupported += "unsupported" in r["classes"]
        for k in c["classes_hit"]:
            clean_cc[k] += 1
        bases.add(c["base"])
        base_domain[c["base"]] = c["domain"]
        if c["replays"] and c.get("replay_ms") is not None:
            lat.append(c["replay_ms"] / len(c["replays"]))
    div = t.get("binding_divergences", [])
    deploy_crashes = cc["deploy_crash"] + clean_cc["deploy_crash"]
    false_alarms = cc["false_alarm"] + clean_cc["false_alarm"]
    return {
        "tamper_cases": len(cases), "tampered_cases": tampered, "compound_cases": compound,
        "applied_classes": dict(applied_classes), "missing_classes": [c for c in tamper.CLASSES if not applied_classes[c]],
        "distinct_bases": len(bases), "bases_by_domain": dict(Counter(base_domain.values())),
        "controls": len(controls), "clean_replays": clean_replays, "clean_verified": clean_ok,
        "class_counts": dict(cc), "clean_class_counts": dict(clean_cc),
        "definite_total": d_total, "definite_detected": d_detected,
        "detection_rate": (d_detected / d_total) if d_total else None,
        "accepted": sum(cc[k] for k in ACCEPT) + clean_cc["continuation_effect"],
        "unanchored_ack": len(t.get("unanchored_acks", [])) + cc["unanchored_ack"],
        "false_alarms": false_alarms, "binding_divergences": len(div), "explain_mismatch": cc["explain_mismatch"] + clean_cc["explain_mismatch"],
        "fallback_to_current": cc["fallback_to_current"], "unsupported": unsupported, "replay_errors": errors,
        "deploy_crashes": deploy_crashes,
        "latency_ms_per_replay": {"p50": _p(lat, 0.5), "p95": _p(lat, 0.95)},
        "clean_verified_ratio": (clean_ok / clean_replays) if clean_replays else None,
    }
