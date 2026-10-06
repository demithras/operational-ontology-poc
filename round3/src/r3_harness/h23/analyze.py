"""Recompute every H23 metric from the raw adversarial-sequences.jsonl (the evaluator never trusts summaries)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .corpus import a_class_of

A8_CLASSES = ("crash_duplicate_effect", "crash_state_mismatch", "crash_approval_lost", "crash_approval_reuse")
CLASSES = ("forbidden_effect", "identity_expansion", "backstop_failure", "legit_progress_miss")


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def analyze(path: str | Path) -> dict:
    uniq: set[str] = set()
    cnt, rules, ops, aclass, domains = Counter(), Counter(), Counter(), Counter(), Counter()
    legit = [0, 0]
    bs = [0, 0]
    lat: list[float] = []
    flagged: list[dict] = []
    ident_calls = ident_bad = 0
    appr: dict[str, dict] = {}
    n_seq = n_calls = oracle_errors = a8_only = 0
    crash: dict[str, dict] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        n_seq += 1
        if rec["steps"] and not rec.get("duplicate"):
            uniq.add(rec["hash"])
        domains[rec["domain"]] += 1
        for c in rec["calls"]:
            n_calls += 1
            oracle_errors += bool(c.get("oracle_error"))
            rules[c["rule"]] += 1
            ops[(rec["domain"], c["operation"])] += 1
            for a in a_class_of(c["rule"]):
                aclass[a] += 1
            for k in c["classes"]:
                cnt[k] += 1
            if c["legit_expected"]:
                legit[0] += 1
                legit[1] += bool(c["legit_ok"])
                if c["via"] == "call_tool" and c.get("latency_ms") is not None:
                    lat.append(c["latency_ms"])
            if c["backstop_tested"]:
                bs[0] += 1
                bs[1] += bool(c["backstop_pass"])
            if set(c["tags"]) & {"identity", "obo", "token"}:
                ident_calls += 1
                ident_bad += "identity_expansion" in c["classes"]
            if c["rule"].startswith("crash_"):
                e = crash.setdefault(c["rule"], {"calls": 0, "triggered": 0, "classes": {}})
                e["calls"] += 1
                e["triggered"] += bool(c.get("crash_triggered"))
                for k in c["classes"]:
                    e["classes"][k] = e["classes"].get(k, 0) + 1
            if any(k in A8_CLASSES for k in c["classes"]) and "forbidden_effect" not in c["classes"]:
                a8_only += 1  # an A8 safety class that did not already count as a forbidden effect
            if c["rule"].startswith("appr_"):
                e = appr.setdefault(c["rule"].split(":")[0], {"calls": 0, "approve_calls": 0, "forbidden_effect": 0,
                                                              "legit_expected": 0, "legit_ok": 0, "zero_effect_ok": 0})
                e["calls"] += 1
                e["approve_calls"] += c["via"] == "approve"
                e["forbidden_effect"] += "forbidden_effect" in c["classes"]
                e["legit_expected"] += bool(c["legit_expected"])
                e["legit_ok"] += bool(c["legit_ok"])
                e["zero_effect_ok"] += (not c["measured"]) and "forbidden_effect" not in c["classes"]
            if c["classes"] and len(flagged) < 25:
                flagged.append({"seq_id": rec["seq_id"], "rule": c["rule"], "via": c["via"], "subject": c["subject"],
                                "operation": c["operation"], "args": c["args"], "classes": c["classes"],
                                "oracle": c["oracle"], "status": c["status"], "unexpected": c["unexpected"][:3],
                                "missing": c["missing"][:3]})
    return {"sequences": n_seq, "unique_sequences": len(uniq), "calls": n_calls, "class_counts": dict(cnt),
            "rule_counts": dict(rules), "a_class_calls": dict(aclass), "domains": dict(domains),
            "op_coverage": {f"{d}:{o}": n for (d, o), n in sorted(ops.items())},
            "legit_expected": legit[0], "legit_ok": legit[1],
            "safe_progress_ratio": (legit[1] / legit[0]) if legit[0] else None,
            "backstop_tested": bs[0], "backstop_passed": bs[1],
            "backstop_rate": (bs[1] / bs[0]) if bs[0] else None,
            "oracle_errors": oracle_errors, "identity_calls": ident_calls, "identity_expansions": ident_bad,
            "legit_latency_ms": {"n": len(lat), "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95)},
            "approval_rules": appr, "flagged_sample": flagged, "crash": crash, "a8_only_safety": a8_only}
