"""Shared helpers for the H25 harness tests (fakes only; never registered)."""
import collections
import functools

from r3_harness.h25.gen_case import run_case
from r3_harness.h25.gen_race import TYPES, run_race
from tests.fakes import h25_fakes

MUTANT_FAKE = {"precedence_inverted": "fake-precinverted", "quorum_weakened": "fake-quorumweak",
               "emergency_no_expiry": "fake-noexpiry", "merit_autofill": "fake-autofill",
               "domain_privilege_branch": "fake-domainbranch"}


@functools.lru_cache(None)
def fake(name):
    return h25_fakes.load(name)


def factory_for(name):
    return lambda m: h25_fakes.load(MUTANT_FAKE[m[0]] if m else name)


def classes(variant, n_cases=250, n_races=45, seed=3):
    """Row/case class counts of a small corpus."""
    c = collections.Counter()
    for i in range(n_cases):
        r = run_case(variant, seed, i)
        c.update(k for row in r["calls"] for k in row["classes"])
        c.update(r["case_classes"])
    for j in range(n_races):
        r = run_race(variant, seed, j, TYPES[j % len(TYPES)])
        c.update(k for row in r["calls"] for k in row["classes"])
        c.update(r["case_classes"])
    return c


def small_pipeline(name, out_root, exp="exp-h25-dev", cases=160, races=18, **kw):
    """Run the whole runner on a fake at dev sizes -> experiment dir."""
    from pathlib import Path

    from r3_harness.h25.runner import run_variant
    out = Path(out_root) / exp / name
    scan = fake(name).sources
    kwargs = dict(nogov=6, mutation_cases=30, mutation_races=10, audit_cases=30, boundary_cases=30,
                  keep_roles=("admin",), scan_sources=scan, oracle_reference=fake("fake-honest"))
    kwargs.update(kw)
    run_variant(factory_for(name), name, out, exp, 1, cases, races, **kwargs)
    return Path(out_root) / exp
