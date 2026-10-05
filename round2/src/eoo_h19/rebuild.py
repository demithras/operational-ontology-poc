"""Rebuild every commit of a repository from Git alone, >= 2 times, in fresh stores with different clocks and orders; compare the hashes.

A rebuild is: a brand-new GitStore over the same repository directory (empty caches, a clock that reads differently in every pass),
asked for ``canonical_hash(commit)`` and ``state_at(commit).state_hash()``. Each commit's hashes must be identical in every pass, must
equal the digest the store reported when it wrote the commit, and the logical state read raw from Git must equal the oracle DAG's state.
"""
from __future__ import annotations

import datetime as dt
import random

from eoo_engine_git import GitStore, Repo

from .oracle import M

CLOCKS = ("2026-01-01T00:00:00+00:00", "2031-06-30T12:34:56+00:00", None)  # None = a ticking clock


def _clock(fixed):
    tick = [0]

    def clk():
        tick[0] += 1
        return fixed or (dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=tick[0])).isoformat()
    return clk


def rebuild(env, commits: list, passes: int = 3, seed: int = 19) -> dict:
    """``commits``: [(sha, oracle-model hash or None, write-time digest or None)] (duplicates by sha allowed)."""
    uniq = {}
    for sha, oh, wd in commits:
        uniq.setdefault(sha, (oh, wd))
    order = sorted(uniq)
    runs = []
    for k in range(passes):
        st = GitStore(Repo(env.store.repo.path), env.package, clock=_clock(CLOCKS[k % len(CLOCKS)]))
        seq = order if k == 0 else (list(reversed(order)) if k == 1 else random.Random(seed + k).sample(order, len(order)))
        runs.append({s: (st.canonical_hash(s), st.state_at(s).state_hash()) for s in seq})
    bad, ok = [], 0
    by_store, by_oracle = {}, {}
    for sha in order:
        oh, wd = uniq[sha]
        ch, sh = {r[sha][0] for r in runs}, {r[sha][1] for r in runs}
        raw_h = M.state_hash(env.raw.logical(sha))
        flags = {"passes_equal": len(ch) == 1 and len(sh) == 1, "write_time_digest": wd is None or {wd} == ch, "oracle_state": oh is None or oh == raw_h}
        by_store.setdefault(runs[0][sha][0], set()).add(raw_h)
        by_oracle.setdefault(raw_h, set()).add(runs[0][sha][0])
        if all(flags.values()):
            ok += 1
        else:
            bad.append({"commit": sha, **flags})
    bij = sum(1 for v in by_store.values() if len(v) > 1) + sum(1 for v in by_oracle.values() if len(v) > 1)
    return {"unique_commits": len(order), "passes": passes, "rebuilds_per_commit": passes, "equal_commits": ok, "unequal_commits": len(bad),
            "mismatches": bad[:25], "hash_bijection_violations": bij, "distinct_states": len(by_oracle),
            "bad_commits": sorted(b["commit"] for b in bad)}
