"""g2-genfix: H24 generators never raise on an empty population (seq-63 @ seed 31 regression + seed 0..49 sweep)."""
import random

from r3_harness.h23.corpus import load_specs
from r3_harness.h24 import gen_graph
from r3_harness.h24.gen_race import Race, TYPES, run_race
from r3_harness.h24.gen_seq import run_sequence
from tests.fakes.h24_fakes import load

SPECS = load_specs()


def test_seq_63_seed_31_regression_world_without_leaf_principals():
    """seq-63 @ seed 31 drew a revoke with the 15% leaf-actor branch in a world whose `leaves` list is empty."""
    r = run_sequence(load("fake-honest"), SPECS, 31, 63)
    assert r["id"] == "seq-63" and r["calls"] and "unsupported" not in r["case_classes"]


def test_official_shape_corpus_has_zero_generator_errors_seeds_0_to_49():
    v, errs = load("fake-honest"), []
    for seed in range(50):
        for i in range(20):  # 1000 sequences here; the 10,000-sequence sweep is run once by the report, not per test run
            try:
                run_sequence(v, SPECS, seed, i)
            except Exception as exc:  # noqa: BLE001
                errs.append((seed, i, f"{type(exc).__name__}: {exc}"))
    assert not errs, errs[:5]


def test_races_of_every_type_never_raise_for_seeds_0_to_9():
    v, errs = load("fake-honest"), []
    for seed in range(10):
        for j in range(len(TYPES) * 2):
            try:
                run_race(v, SPECS, seed, j, TYPES[j % len(TYPES)])
            except Exception as exc:  # noqa: BLE001
                errs.append((seed, j, f"{type(exc).__name__}: {exc}"))
    assert not errs, errs[:5]


def test_race_chain_survives_an_exhausted_principal_pool():
    """Known-negative for the old behaviour (rng.choice on []): a pool smaller than the depth ends the chain early."""
    race = Race(load("fake-honest"), SPECS, 1, 0, "RV")
    try:
        q = sorted(race.info["holders"])[0]
        keep = {q, "dp-0", "dp-1"}
        race.world = {**race.world, "principals": [p for p in race.world["principals"] if p["id"] in keep]}
        op, args = race.pick(q)
        edges = race.chain(q, [(op["name"], args)], 8)
    finally:
        race.env.close()
    assert 1 <= len(edges) <= 2 and not edges[-1]["redelegable"]
