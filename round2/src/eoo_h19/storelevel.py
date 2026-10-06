"""The store-level corpus: scenarios in batches (one temporary repository per batch), rebuilds per repository, check tallies."""
from __future__ import annotations

import time

from .execute import run_scenario
from .rebuild import rebuild
from .seed import Env

CHECKS = ("rebuild_hash_equal", "no_lost_update", "oracle_outcome_agreement", "conflict_explicit_replayable", "ref_unchanged_on_refusal",
          "binding_pinned", "no_rebinding_accepted")


def run_corpus(scenarios: list, *, batch: int = 250, ir_version=None, log=print) -> dict:
    rows, rb, fsck, t0 = [], {"unique_commits": 0, "equal_commits": 0, "unequal_commits": 0, "mismatches": [], "hash_bijection_violations": 0,
                              "distinct_states": 0, "passes": 3, "rebuilds_per_commit": 3, "bad_commits": []}, [], time.time()
    for b0 in range(0, len(scenarios), batch):
        env = Env(ir_version=ir_version)
        commits = []
        for i, sc in enumerate(scenarios[b0:b0 + batch]):
            r, c = run_scenario(env, sc, f"{b0 + i:05d}")
            rows.append(r)
            commits += c
        one = rebuild(env, commits)
        for k in ("unique_commits", "equal_commits", "unequal_commits", "hash_bijection_violations", "distinct_states"):
            rb[k] += one[k]
        rb["mismatches"] = (rb["mismatches"] + one["mismatches"])[:25]
        rb["bad_commits"] += one["bad_commits"]
        rb["passes"] = rb["rebuilds_per_commit"] = min(rb["passes"], one["passes"])
        fsck.append(env.raw.fsck())
        env.close()
        log(f"[store] {min(b0 + batch, len(scenarios))}/{len(scenarios)} scenarios {time.time() - t0:.0f}s")
    return {"scenarios": rows, "rebuild": rb, "fsck": fsck}


def tally(res: dict) -> dict:
    """Numbers recomputed from the per-write rows (never from a summary)."""
    t = {k: 0 for k in ("scenarios", "writes", "ok", "conflict", "rejected", "stale_writes", "lost_updates", "silent_wrong_accept", "false_conflicts",
                        "outcome_disagreements", "replays", "replays_equal", "ref_moved_on_refusal", "digest_unstable", "binds", "binds_pinned",
                        "rebind_attempts", "rebind_accepted", "exceptions", "binds_with_later_change")}
    t["classes"] = {}
    for r in res["scenarios"]:
        t["scenarios"] += 1
        t["exceptions"] += bool(r["exc"])
        for c in r["classes"]:
            t["classes"][c] = t["classes"].get(c, 0) + 1
        for w in r["w"]:
            t["writes"] += 1
            t[w["g"]] += 1
            t["stale_writes"] += w["s"]
            t["lost_updates"] += w["L"]
            t["outcome_disagreements"] += 1 - w["a"]
            t["silent_wrong_accept"] += w["g"] == "ok" and w["x"] != "ok"
            t["false_conflicts"] += w["g"] == "conflict" and w["x"] == "ok"
            t["ref_moved_on_refusal"] += 1 - w["ref_ok"]
            t["digest_unstable"] += 1 - w["D"]
            if "r" in w:
                t["replays"] += 1
                t["replays_equal"] += w["r"] == "eq"
            if w["t"] == "rebind":
                t["rebind_attempts"] += 1
                t["rebind_accepted"] += w.get("rebound", 0)
        t["binds"] += len(r["binds"])
        t["binds_pinned"] += sum(b["pinned"] for b in r["binds"])
        t["binds_with_later_change"] += sum(1 for b in r["binds"] if b["after"])
    return t


def failures(res: dict) -> dict:
    """check name -> number of violations (0 = the check holds on this corpus)."""
    t, rb = tally(res), res["rebuild"]
    return {"rebuild_hash_equal": rb["unequal_commits"] + t["digest_unstable"] + rb["hash_bijection_violations"],
            "no_lost_update": t["lost_updates"] + t["silent_wrong_accept"],
            "oracle_outcome_agreement": t["outcome_disagreements"],
            "conflict_explicit_replayable": t["replays"] - t["replays_equal"],
            "ref_unchanged_on_refusal": t["ref_moved_on_refusal"],
            "binding_pinned": t["binds"] - t["binds_pinned"],
            "no_rebinding_accepted": t["rebind_accepted"]}
