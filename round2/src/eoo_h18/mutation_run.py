"""Run the registered mutants and a clean control (before and after) over the same generated corpus."""
from __future__ import annotations

import random
import tempfile

from .gen import case_hash, gen_case
from .mutants import REGISTRY
from .rig import EooRig


def count(rows: list, expect: dict) -> int:
    n = 0
    for r in rows:
        k = expect["kind"]
        if k == "illegal_accepted":
            hit = r.get("divergence") == "illegal_accepted" and r["op"] == expect["op"] and (
                "class_tag" not in expect or expect["class_tag"] in r["classes"])
        elif k == "summary_mismatch":
            hit = r["op"] == expect["op"] and expect["field"] in r.get("summary_diff", ())
        else:
            hit = bool(r.get("accepted")) and not all(r.get("trace", {"x": False}).values())
        n += bool(hit)
    return n


def corpus(rig: EooRig, seed: int, n: int) -> list:
    rnd, out, seen = random.Random(seed), [], set()
    while len(out) < n:
        c = gen_case(rnd, rig.base_ops, rig.commit0)
        if case_hash(c) not in seen:
            seen.add(case_hash(c))
            out.append(c)
    return out


def run_rows(reader, cases: list, *, mutate=None, provenance=True, ir_version=None) -> list:
    rig = EooRig(tempfile.mkdtemp(prefix="eoo-h18-mut-"), reader=reader, mutate=mutate, provenance=provenance, ir_version=ir_version)
    return [r for c in cases for r in rig.run_case(c, case_hash(c))]


def run_mutations(reader, seed: int = 1801, n: int = 250, ir_version=None) -> dict:
    probe = EooRig(tempfile.mkdtemp(prefix="eoo-h18-mutp-"), reader=reader, ir_version=ir_version)
    cases = corpus(probe, seed, n)
    expects = [m["expect"] for m in REGISTRY]

    def signals(rows):
        return [count(rows, e) for e in expects]
    control = run_rows(reader, cases, ir_version=ir_version)
    c0 = signals(control)
    out = []
    for m in REGISTRY:
        rows = run_rows(reader, cases, mutate=m["mutate"], provenance=m["provenance"], ir_version=ir_version)
        hit, base = count(rows, m["expect"]), c0[REGISTRY.index(m)]
        fails = [r for r in rows if r.get("exception")]
        out.append({"id": m["id"], "class": m["class"], "target": m["target"], "expected_signal": m["expect"], "signal_count": hit,
                    "control_signal_count": base, "killed": hit > 0 and base == 0, "steps": len(rows), "exceptions": len(fails)})
    after = signals(run_rows(reader, cases, ir_version=ir_version))
    return {"corpus_cases": n, "seed": seed, "controls": {"clean": not any(c0), "clean_after": not any(after), "signals_before": c0, "signals_after": after},
            "mutants": out}
