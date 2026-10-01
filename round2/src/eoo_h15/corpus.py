"""Fixed-seed Hypothesis generation of valid IR packages, corpus hash, feature coverage, shrinking."""
from __future__ import annotations

import hashlib
from collections import Counter

from hypothesis import HealthCheck, Phase, find, seed as hseed, settings, given

from eoo_ir import validate
from eoo_ir.strategies import valid_packages

from .isolation import isolated_constants
from .roundtrip import attempt, norm_path
from .util import canon


def generate(n: int, seed: int, consume) -> int:
    """Call consume(index, pkg) for n generated packages (fixed seed, no database, generate phase only).
    consume must not raise; returns how many valid examples Hypothesis produced."""
    box = {"i": 0}

    @hseed(seed)
    @settings(max_examples=n, database=None, deadline=None, phases=[Phase.generate],
              suppress_health_check=list(HealthCheck))
    @given(valid_packages())
    def run(pkg):
        consume(box["i"], pkg)
        box["i"] += 1

    with isolated_constants():
        run()
    return box["i"]


class CorpusHash:
    def __init__(self):
        self.h = hashlib.sha256()
        self.seen: set[str] = set()
        self.n = 0
        self.invalid = 0

    def add(self, pkg: dict) -> None:
        c = canon(pkg)
        d = hashlib.sha256(c.encode()).hexdigest()
        self.h.update(d.encode() + b"\n")
        self.seen.add(d)
        self.n += 1
        if validate(pkg):
            self.invalid += 1

    def result(self) -> dict:
        return {"generated": self.n, "unique": len(self.seen), "invalid_under_validate": self.invalid,
                "corpus_sha256": self.h.hexdigest()}


def features(pkg: dict) -> list[str]:
    """Names of the IR features a package exercises (coverage view of the generated corpus)."""
    f = []
    for k in ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
              "observation_types", "constraints"):
        if pkg.get(k):
            f.append("has:" + k)
    if pkg.get("imports"):
        f.append("has:imports")
    if "metadata" in pkg:
        f.append("has:metadata")
    if "domain_id" in pkg:
        f.append("has:domain_id")
    fn_ids = {x["id"] for x in pkg.get("functions", [])}
    if fn_ids & {x["id"] for x in pkg.get("actions", [])}:
        f.append("function_and_action_share_id")
    for lk in pkg.get("link_types", []):
        for side in ("from_cardinality", "to_cardinality"):
            c = lk[side]
            f.append("card_max:" + ("*" if c["max"] == "*" else "int"))
            f.append("card_min:" + ("0" if c["min"] == 0 else "pos"))
    for a in pkg.get("actions", []):
        f.append("action_idempotency:" + a["idempotency"])
        if a.get("authority_refs"):
            f.append("action:authority_refs")
        if a.get("policy_refs"):
            f.append("action:policy_refs")
        if "compensation_action" in a:
            f.append("action:compensation=" + ("null" if a["compensation_action"] is None else "ref"))
        for e in a["effects"]:
            f.append("effect:" + e["operation"])
    for fn in pkg.get("functions", []):
        if "determinism" in fn:
            f.append("function_determinism:" + fn["determinism"])
    for p in pkg.get("policies", []):
        f.append("policy_decision:" + p["decision"])
    for r in pkg.get("authority_rules", []):
        f.append("authority_effect:" + r["effect"])
        if "delegation_allowed" in r:
            f.append("authority:delegation_allowed")
    for c in pkg.get("constraints", []):
        f.append("constraint_severity:" + c["severity"])
    return sorted(set(f))


def coverage(counter: Counter) -> dict:
    return dict(sorted(counter.items()))


def shrink_counterexamples(surface, seed: int, signatures: list[str], max_n: int = 20, max_examples: int = 3000) -> list[dict]:
    """Hypothesis-shrunk minimal failing package per distinct failure signature (an IR path or error code)."""
    out = []
    for sig in signatures[:max_n]:
        def bad(pkg, sig=sig):
            r = attempt(surface, pkg)
            return r["status"] == "failed" and sig in r["paths"]
        try:
            with isolated_constants():
                pkg = find(valid_packages(), bad, settings=settings(max_examples=max_examples, database=None, deadline=None,
                           suppress_health_check=list(HealthCheck), derandomize=True))
        except Exception as e:  # noqa: BLE001 - Unsatisfiable: could not re-find within the budget
            out.append({"signature": sig, "minimal": None, "note": f"not re-found within {max_examples} examples ({type(e).__name__})"})
            continue
        r = attempt(surface, pkg)
        out.append({"signature": sig, "minimal": pkg, "kind": r["kind"], "detail": r.get("detail"), "paths": r["paths"]})
    return out
