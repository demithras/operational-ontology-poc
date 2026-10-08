"""Recompute every H25 number from the raw rows (cases-h25.jsonl.gz). The evaluator never trusts a summary file."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from r3_shared.governance import structural_signature

from .gen_model import DOMAINS, fixture

CASES_FILE = "cases-h25.jsonl.gz"
FILES = ("authority-topology-corpus.json", "oracle-differential.json", "domain-branch-audit.json",
         "oracle-boundary-audit.json", "mutation-results.json")
EXTRA = ("safe-progress.json", CASES_FILE)
MODELS = ("hierarchical", "collegial", "polycentric")
RULES = ("decision", "review", "lapse", "emergency")
TAG = re.compile(r"^(\w+):(DENIED|INVALID):(\w+)$")
BASE_REASONS = {"token", "schema", "no_governance", "duplicate_case", "not_governed", "matter_conflict", "no_authority",
                "unknown_case", "not_eligible", "stage_closed", "already_judged", "oracle_needed", "not_requester",
                "case_denied", "case_required", "precedence_unresolved"}
REVIEW_REASONS = {"not_decided", "not_party", "already_appealed", "window_closed", "not_final"}
EMERGENCY_REASONS = {"scope_amplification", "emergency_too_long", "not_grantee", "emergency_inactive",
                     "out_of_emergency_scope", "emergency_expired"}


def reachable(model: str) -> dict:
    """Outcome rules and refusal classes reachable in a model family (from the frozen fixtures, both domains)."""
    docs = [fixture(model, d) for d in DOMAINS]
    rules = {"decision"}
    reasons = set(BASE_REASONS)
    for d in docs:
        ms = [m for m in d["matters"] if not (d["emergency"] and m["id"] == d["emergency"]["matter"])]
        if any(m["review"] for m in ms):
            rules.add("review")
            reasons |= REVIEW_REASONS
        if any(m["review"] is None for m in ms):
            reasons.add("not_reviewable")
        if any(m["on_absent"] != "await" for m in ms):
            rules.add("lapse")
        if d["emergency"]:
            rules.add("emergency")
            reasons |= EMERGENCY_REASONS
    return {"rules": sorted(rules), "reasons": sorted(reasons)}


def signature(model: str, domain: str = "manufacturing") -> dict:
    s = structural_signature(fixture(model, domain))
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in s.items()}


def read_cases(vdir: Path):
    with gzip.open(vdir / CASES_FILE, "rt") as fh:
        for line in fh:
            yield json.loads(line)


def _pct(xs: list[float], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def analyze(vdir: Path) -> dict:
    cc: dict[str, int] = {}
    digests: set[str] = set()
    per_model = {m: {"cases": 0, "domains": set(), "rules": set(), "reasons": set()} for m in MODELS}
    n_cases = n_actions = redraws = 0
    awaiting = conflicts = unresolved = appeals = emerg = emerg_late = race_cases = overlapping = 0
    ok_legit = loss = 0
    lat: list[float] = []
    race_types: dict[str, int] = {}
    kinds = {"nogov": 0}
    for c in read_cases(vdir):
        n_cases += 1
        digests.add(c["digest"])
        redraws += c.get("redraws", 0)
        pm = per_model.get(c["model"])
        tags = set(c["tags"])
        if pm is not None:
            pm["cases"] += 1
            pm["domains"].add(c["domain"])
            for t in tags:
                m = TAG.match(t)
                if m:
                    pm["reasons"].add(m.group(3))
            if "request:DENIED:case_required" in tags:
                pm["reasons"].add("case_required")
            for cid, f in c["final"].items():
                if f[3] and f[2]:
                    pm["rules"].add(f[2])
        rows = c["calls"]
        n_actions += len(rows)
        for r in rows:
            for k in r["classes"]:
                cc[k] = cc.get(k, 0) + 1
            if r.get("action") in ("execute", "act") and r.get("committed"):
                if pm is not None and r["action"] == "act":
                    pm["rules"].add("emergency")
                if not (set(r["classes"]) - {"ok", "race_refusal_ok"}):
                    ok_legit += 1
                    if r.get("lat_ms") is not None:
                        lat.append(r["lat_ms"])
        for k in c["case_classes"]:
            cc[k] = cc.get(k, 0) + 1
        loss += sum(1 for r in rows if "progress_loss" in r["classes"])
        if "execute:DENIED:oracle_needed" in tags:
            awaiting += 1
        if "prec_conflict" in tags:
            conflicts += 1
        if "propose:DENIED:precedence_unresolved" in tags:
            unresolved += 1
        if "appeal:OK:None" in tags:
            appeals += 1
        if "declare:OK:None" in tags:
            emerg += 1
            if tags & {"act:DENIED:emergency_expired", "act:DENIED:emergency_inactive"}:
                emerg_late += 1
        if c["id"].startswith("race-"):
            race_types[c["type"]] = race_types.get(c["type"], 0) + 1
            if c.get("race"):
                race_cases += 1
                overlapping += bool(c.get("overlap"))
        if c["id"].startswith("nogov-") or "no_governance" in "".join(tags):
            kinds["nogov"] += 1
    return {
        "cases": n_cases, "unique_cases": len(digests), "actions": n_actions, "class_counts": dict(sorted(cc.items())),
        "redraws": redraws, "oracle_needed_cases": awaiting, "precedence_conflict_cases": conflicts,
        "precedence_unresolved_cases": unresolved, "appeal_cases": appeals, "emergency_cases": emerg,
        "emergency_late_act_cases": emerg_late, "race_cases": race_cases, "race_overlapping": overlapping,
        "race_types": race_types, "nogov_cases": kinds["nogov"],
        "models": {m: {"cases": v["cases"], "domains": sorted(v["domains"]), "rules": sorted(v["rules"]),
                       "reasons": sorted(v["reasons"]), "signature": signature(m), "reachable": reachable(m)}
                   for m, v in per_model.items()},
        "progress": {"legit_committed": ok_legit, "progress_loss": loss,
                     "ratio": (ok_legit / (ok_legit + loss)) if ok_legit + loss else None},
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "n": len(lat)},
    }
