"""Generate >= N unique lifecycle cases (Hypothesis-driven randomness) and execute each through EOO and the baseline."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from hypothesis import HealthCheck, Phase, given, seed as hseed, settings, strategies as st

from eoo_exp.util import canon, sha_text

from .base_run import run_case_baseline
from .gen import case_hash, gen_case
from .rig import EooRig

CORE_CLASSES = ("post_freeze_threshold_edit", "evidence_wrong_version", "evidence_unpinned", "verdict_without_evidence", "forced_verdict",
                "incomplete_preregistration", "blank_freeze", "flag_non_orphan", "start_out_of_order", "supersede_non_evaluated")
REQUIRED_CLASSES = CORE_CLASSES + ("supersede_self", "new_version_overwrite", "decision_blank_rationale", "evidence_pinned_ok", "evaluate_with_evidence",
                                   "supersede_ok", "flag_orphan", "preregister", "decision_ok")


def generate(rig: EooRig, seed0: int, n: int) -> tuple[list, dict]:
    seen, cases, dupes, batch = set(), [], 0, 0
    while len(cases) < n and batch < 20:
        want = max(50, int((n - len(cases)) * 1.1))

        def sink(rnd):
            nonlocal dupes
            c = gen_case(rnd, rig.base_ops, rig.commit0)
            h = case_hash(c)
            if h in seen:
                dupes += 1
                return
            seen.add(h)
            cases.append(c)

        @hseed(seed0 + batch)
        @settings(max_examples=want, database=None, deadline=None, phases=[Phase.generate], suppress_health_check=list(HealthCheck))
        @given(st.randoms(use_true_random=False))
        def body(rnd):
            sink(rnd)
        body()
        batch += 1
    cases = cases[:n]
    return cases, {"requested_unique": n, "unique_cases": len(cases), "duplicates_skipped": dupes, "batches": batch, "seed": seed0,
                   "corpus_hash": sha_text(canon(sorted(case_hash(c) for c in cases)))}


def compact(e: dict, b: dict) -> dict:
    out = {"op": e["op"], "cls": e["classes"], "legal": e["oracle_legal"],
           "eoo": {"acc": e["accepted"], "state": e["state"], "gate": e.get("denied_gate"), "div": e.get("divergence"), "match": e["summary_match"],
                   "commits": e["new_commits"], "unchanged": e["engine_store_unchanged"], "git_only": e["effects_all_git"],
                   "trace": all(e["trace"].values()) if "trace" in e else None, "exc": e["exception"]},
           "base": {"acc": b["accepted"], "div": b.get("divergence"), "match": b["summary_match"], "exc": b["exception"]}}
    if e["op"] == "evaluate" and e["accepted"]:
        out["verdict"] = (e["summary"]["verdicts"] or [None])[-1]
    return out


def execute(rig: EooRig, cases: list, log=print) -> list:
    out, t0 = [], time.time()
    for k, c in enumerate(cases):
        h = case_hash(c)
        erows = rig.run_case(c, h)
        brows = run_case_baseline(c, rig.store.files_at(rig.last_start), rig.evaluators)
        out.append({"id": h, "subject": c["subject"], "phase0": c["phase0"], "n_ops": len(c["ops"]), "steps": [
            compact(e, b) for e, b in zip(erows, brows)], "stopped_eoo": len(erows) < len(c["ops"]), "stopped_base": len(brows) < len(c["ops"])})
        if k % 100 == 0:
            log(f"[corpus] {k}/{len(cases)} cases {time.time() - t0:.0f}s")
    return out


def aggregate(results: list) -> dict:
    """All numbers recomputed from the per-step rows."""
    steps = [(r["id"], i, s) for r in results for i, s in enumerate(r["steps"])]
    out: dict = {}
    for who in ("eoo", "base"):
        by_cls: dict = defaultdict(lambda: Counter())
        div, states, gates = [], Counter(), Counter()
        for cid, i, s in steps:
            v = s[who]
            states[v.get("state") or ("ACCEPTED" if v["acc"] else "REFUSED")] += 1
            if v.get("gate"):
                gates[v["gate"]] += 1
            for c in s["cls"] + ["*"]:
                by_cls[c]["n"] += 1
                by_cls[c]["legal"] += s["legal"]
                by_cls[c]["accepted"] += v["acc"]
                by_cls[c]["illegal_accepted"] += v["div"] == "illegal_accepted"
                by_cls[c]["legal_rejected"] += v["div"] == "legal_rejected"
                by_cls[c]["state_mismatch"] += not v["match"]
            if v["div"] or not v["match"] or v["exc"]:
                div.append({"case": cid, "step": i, "op": s["op"], "classes": s["cls"], "oracle_legal": s["legal"], "accepted": v["acc"],
                            "divergence": v["div"], "summary_match": v["match"], "exception": v["exc"]})
        tot = by_cls["*"]
        out[who] = {"steps": tot["n"], "accepted": tot["accepted"], "illegal_accepted": tot["illegal_accepted"], "legal_rejected": tot["legal_rejected"],
                    "state_mismatches": tot["state_mismatch"], "exceptions": sum(1 for _, _, s in steps if s[who]["exc"]),
                    "agreement": round(1 - (tot["illegal_accepted"] + tot["legal_rejected"]) / max(1, tot["n"]), 6),
                    "illegal_accepted_core": sum(by_cls[c]["illegal_accepted"] for c in CORE_CLASSES if c in by_cls),
                    "by_class": {k: dict(v) for k, v in sorted(by_cls.items()) if k != "*"}, "states": dict(states), "denied_by_gate": dict(gates),
                    "divergence_examples": div[:25], "divergence_total": len(div)}
    ev = [s for _, _, s in steps if s["op"] == "evaluate" and s["eoo"]["acc"]]
    out["evaluations"] = {"accepted_evaluations": len(ev), "verdict_matches_oracle": sum(1 for s in ev if s["eoo"]["match"]),
                          "verdicts": dict(Counter(s.get("verdict") for s in ev))}
    acc = [s["eoo"] for _, _, s in steps if s["eoo"]["acc"]]
    out["trace"] = {"accepted_actions": len(acc), "one_commit_each": sum(1 for a in acc if a["commits"] == 1), "trace_ok": sum(1 for a in acc if a["trace"]),
                    "ontology_only_writes": sum(1 for _, _, s in steps if not s["eoo"]["unchanged"]),
                    "non_git_effects": sum(1 for _, _, s in steps if not s["eoo"]["git_only"]),
                    "commits_without_acceptance": sum(1 for _, _, s in steps if s["eoo"]["commits"] and not s["eoo"]["acc"]),
                    "refused_with_commit": sum(1 for _, _, s in steps if not s["eoo"]["acc"] and s["eoo"]["commits"])}
    out["class_counts"] = {k: out["eoo"]["by_class"].get(k, {}).get("n", 0) for k in REQUIRED_CLASSES}
    out["variants_disagree"] = sum(1 for _, _, s in steps if s["eoo"]["acc"] != s["base"]["acc"])
    return out
