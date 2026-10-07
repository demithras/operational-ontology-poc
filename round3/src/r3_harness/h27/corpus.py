"""Base histories and the tamper/clean plan (B2/B3). Deterministic from the run seed."""
from __future__ import annotations

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


def plan(rng: random.Random, n_cases: int, n_bases: int) -> list[tuple[list[str], int]]:
    """>= 25% compound cases (2-4 classes of T1-T8), T9 at most once per base, every single class cycled."""
    t9 = list(range(n_bases))
    rng.shuffle(t9)
    out, single = [], 0
    for i in range(n_cases):
        if i % 4 == 3:
            out.append((sorted(rng.sample(tamper.SINGLE, rng.randint(2, 4))), i % n_bases))
        elif i % 9 == 8 and t9:
            out.append((["T9"], t9.pop()))
        else:
            out.append(([tamper.SINGLE[single % len(tamper.SINGLE)]], i % n_bases))
            single += 1
    return out


def run_plan(variant, anchor, bases: list, pl, work: str, seed: int, tag: str = "t"):
    for i, (classes, bi) in enumerate(pl):
        yield case_mod.run_case(bases[bi], variant, anchor, os.path.join(work, f"{tag}{i}"), f"{tag}{i}",
                                seed * 7919 + i, classes)


def run_clean(variant, anchor, bases: list, work: str, seed: int, n: int, tag: str = "c"):
    for i in range(n):
        yield case_mod.run_case(bases[i % len(bases)], variant, anchor, os.path.join(work, f"{tag}{i}"), f"{tag}{i}",
                                seed * 104729 + i, [])
