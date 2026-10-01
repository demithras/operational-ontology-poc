"""Shared helpers for the oracle self-tests (not a test module)."""
from __future__ import annotations

from functools import lru_cache

from hypothesis import HealthCheck, given, settings

from eoo_ir.mutations import REGISTRY, apply_class
from eoo_ir.strategies import valid_packages


@lru_cache(maxsize=4)
def sample_packages(n: int = 150, seed_tag: int = 0) -> tuple:
    """Deterministic sample of n generated valid packages (fixed seed via derandomize)."""
    out: list[dict] = []

    @settings(max_examples=n, derandomize=True, database=None, deadline=None, suppress_health_check=list(HealthCheck))
    @given(valid_packages())
    def collect(p):
        out.append(p)

    collect()
    return tuple(out)


def sweep_mutations(pkgs, equiv, seeds=(1, 2)) -> dict:
    """For every mutation class: how often applicable, and the packages the oracle wrongly judged equivalent
    or whose diffs did not name the mutated field."""
    stats = {cid: {"applied": 0, "equiv_missed": [], "field_missed": []} for cid in REGISTRY}
    for pkg in pkgs:
        for cid, mc in REGISTRY.items():
            for seed in seeds:
                m = apply_class(cid, pkg, seed)
                if m is None:
                    continue
                stats[cid]["applied"] += 1
                res = equiv(pkg, m)
                if res.ok:
                    stats[cid]["equiv_missed"].append((pkg, m))
                elif not any(f in d for d in res.diffs for f in mc.field.split("|")):
                    stats[cid]["field_missed"].append((res.diffs[:3], mc.field))
    return stats
