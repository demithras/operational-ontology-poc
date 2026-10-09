"""Finalize phase (OUTSIDE the sandbox, after ExternalWorld close()): the oracle reads the closed ledger, every record is judged,
and the five contract evidence files are written. Everything the evaluator needs is recomputable from cases.jsonl + the ledger."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from r3_oracle import extoracle

from . import judge, specs
from .runner import RAW

PRIMS_FLOOR = ("L1", "L2", "L3", "T1", "T2", "T3", "R1", "R2", "O1", "O2", "G1", "G2", "G3")


def load_raw(out: Path):
    cases, recs, harness = {}, defaultdict(dict), []
    for line in (out / RAW).read_text().splitlines():
        d = json.loads(line)
        if "case_def" in d:
            cases[d["case_def"]["id"]] = d["case_def"]
        elif "harness_row" in d:
            harness.append(d)
        else:
            recs[d["case"]][d["kind"]] = d
    return cases, recs, harness


def sysstate_check(ledger: dict, sysseed: dict) -> dict:
    seed = {tuple(k.split("|", 1)): v for k, v in sysseed.items()}
    combined = specs.combined_systems()
    exp = extoracle.sysstate_expected(combined, ledger, seed)
    got = ledger["sysstate"]
    keys = set(exp) | set(got)
    bad = sorted(f"{s}|{k}" for s, k in keys if exp.get((s, k)) != got.get((s, k)))
    return {"replay_equals_sysstate": not bad, "mismatching_keys": bad[:20], "keys": len(keys)}


def judge_all(out: Path, ext_dir: str, pre: dict) -> dict:
    cases, recs, harness = load_raw(out)
    ledger = extoracle.load_ledger(ext_dir)
    led = judge.LedgerIndex(ledger)
    intents_by_dep: dict = defaultdict(list)
    for cid, kinds in recs.items():
        for R in kinds.values():
            for q in R["requests"]:
                if not q["replay"]:
                    intents_by_dep[R["dep"]] += q["intents"]
    scope_all = extoracle.scope_check(ledger, intents_by_dep)
    rows = []
    for cid in sorted(recs):
        kinds = recs[cid]
        B = kinds.get("byz")
        if B is None:
            continue
        sd = specs.load(B["domain"])[2]
        rows.append(judge.judge_case(B, kinds.get("twin"), led, sd, scope_all))
    known = {R["dep"] for kinds in recs.values() for R in kinds.values()}
    return {"cases": cases, "recs": recs, "rows": rows, "ledger": ledger, "harness_rows": harness, "scope_all": scope_all,
            "unattributed_scope": [r["seq"] for r in scope_all if r["deployment"] not in known],
            "sysstate": sysstate_check(ledger, pre["sysseed"])}


def aggregate(J: dict) -> dict:
    rows, cases = J["rows"], J["cases"]
    byz = [r for r in rows if r["case"].startswith("byz")]
    ctlr = [r for r in rows if r["case"].startswith("control")]
    clean = [r for r in byz if not r["harness"]]
    by_class: dict[str, list] = {c: sorted(r["case"] for r in rows if r["classes"].get(c)) for c in judge.CLASSES}
    gov_sub = Counter(g["sub"] for r in rows for g in r["gov"])
    det = [sum(r["detect"][0] for r in clean), sum(r["detect"][1] for r in clean)]
    harness = Counter(h for r in rows for h in set(r["harness"]))
    harness["generator_redraw_exhausted"] += len(J["harness_rows"])
    floors = {"per_primitive": {p: sum(p in r["prims"] for r in clean) for p in PRIMS_FLOOR},
              "per_domain_system": dict(Counter(f"{r['domain']}/{r['system']}" for r in clean)),
              "crash_cases": sum(bool(r["crash"]) for r in clean),
              "none_class_cases": sum(r["system"] == "GEN-NULL" for r in clean),
              "observer_fault_cases": sum(bool(cases[r["case"]].get("fault")) for r in clean),
              "byzantine_cases": len(clean), "honest_controls": len(ctlr),
              "controls_observed": {d: sum(1 for r in ctlr if r["domain"] == d and r["observed_effects"] > 0) for d in specs.DOMAINS},
              "outcome_points": sum(r["points"] for r in rows), "outcome_equal": sum(r["equal"] for r in rows),
              "progress_checked": sum(1 for r in clean if not r["crash"] and r["system"] != "GEN-NULL") + len(ctlr)}
    return {"classes": {c: {"cases": len(v), "count": sum(r["classes"].get(c, 0) for r in rows), "case_ids": v}
                        for c, v in by_class.items()},
            "governance_sub": dict(gov_sub), "detection": {"attempted": det[0], "detected": det[1]}, "harness": dict(harness),
            "floors": floors, "unattributed_scope_rows": J["unattributed_scope"], "sysstate": J["sysstate"],
            "byzantine_cases": len(byz), "judged_cases": len(rows)}
