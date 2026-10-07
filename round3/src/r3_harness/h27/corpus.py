"""Base histories and the tamper/clean plan (B2/B3). Deterministic from the run seed."""
from __future__ import annotations

import itertools
import os
import random

from r3_shared.authspec import load_auth_spec
from r3_shared.opsspec import load_ops_spec

from . import base as base_mod
from . import case as case_mod
from . import tamper
from .gen_history import build_history

DOMAINS = ("manufacturing", "project")


def build_bases(variant, anchor, work: str, seed: int, per_domain: int, decisions=(5, 30), tag: str = "b") -> list:
    rng = random.Random(seed)
    specs = {d: (load_ops_spec(d), load_auth_spec(d)) for d in DOMAINS}
    out = []
    for i in range(per_domain * len(DOMAINS)):
        dom = DOMAINS[i % 2]
        ops, auth = specs[dom]
        bseed = seed * 1_000_003 + i
        n = rng.randint(*decisions)
        s = build_history(variant, dom, ops, auth, os.path.join(work, f"{tag}{i}"), anchor, bseed, n, v2=(i // 2) % 3 == 0)
        out.append(base_mod.analyze(s, anchor, f"{tag}{i}"))
    return out


def plan_iter(rng: random.Random, n_bases: int):
    """Endless plan: >= 25% compound cases (2-4 classes of T1-T8), T9 at most once per base, every single class cycled."""
    t9 = list(range(n_bases))
    rng.shuffle(t9)
    single = 0
    for i in itertools.count():
        if i % 4 == 3:
            yield sorted(rng.sample(tamper.SINGLE, rng.randint(2, 4))), i % n_bases
        elif i % 9 == 8 and t9:
            yield ["T9"], t9.pop()
        else:
            yield [tamper.SINGLE[single % len(tamper.SINGLE)]], i % n_bases
            single += 1


def plan(rng: random.Random, n_cases: int, n_bases: int) -> list[tuple[list[str], int]]:
    return list(itertools.islice(plan_iter(rng, n_bases), n_cases))


def effective(rec: dict) -> bool:
    """A case counts only if a primitive really changed the store (or a continuation probe ran)."""
    return bool(rec["applied"]) and bool(rec["definite"] or "continuation" in rec["flags"])


def run_effective(variant, anchor, bases: list, work: str, seed: int, n: int, stats: dict, tag: str = "t", rng=None):
    """Yield `n` EFFECTIVE tamper cases (no-op attempts are dropped and counted in stats); gives up at 4n attempts."""
    rng = rng or random.Random(seed + 1)
    got = 0
    for i, (classes, bi) in enumerate(plan_iter(rng, len(bases))):
        if got >= n or i >= 4 * n:
            break
        stats["attempts"] = i + 1
        rec = case_mod.run_case(bases[bi], variant, anchor, os.path.join(work, f"{tag}{i}"), f"{tag}{i}", seed * 7919 + i, classes)
        if effective(rec):
            got += 1
            yield rec
        else:
            stats["noops"] = stats.get("noops", 0) + 1


def run_plan(variant, anchor, bases: list, pl, work: str, seed: int, tag: str = "t"):
    for i, (classes, bi) in enumerate(pl):
        yield case_mod.run_case(bases[bi], variant, anchor, os.path.join(work, f"{tag}{i}"), f"{tag}{i}",
                                seed * 7919 + i, classes)


def run_clean(variant, anchor, bases: list, work: str, seed: int, n: int, tag: str = "c"):
    for i in range(n):
        yield case_mod.run_case(bases[i % len(bases)], variant, anchor, os.path.join(work, f"{tag}{i}"), f"{tag}{i}",
                                seed * 104729 + i, [])
