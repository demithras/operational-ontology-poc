"""H26 generators: never raise (seed sweep 0..1999), pairs are low-equivalent by oracle construction, equal-shape worlds."""
import random

import pytest

from r3_harness.h26 import gen_auth, gen_pair, sim
from r3_oracle.disclosure import Facts, low_view
from r3_shared.authspec import validate_strict


def test_seed_sweep_never_raises_and_every_pair_is_oracle_valid():
    made = skipped = errors = 0
    kinds = set()
    for seed in range(2000):
        p, st = gen_pair.draw(seed, seed % 7 + 7 * (seed % 3))
        errors += "gen_error" in st
        if p is None:
            skipped += st["skipped"]
            continue
        made += 1
        kinds.update(p["kinds"])
        ops, _a, _g = gen_pair.load(p["domain"])
        base = sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])
        d1, d2 = p["w"]
        assert [len(b) for b in d1["batches"]] == [len(b) for b in d2["batches"]]  # D2: equal transaction shape
        assert len(d1["high"]) == len(d2["high"]) and len(d1["edges"]) == len(d2["edges"]) and len(d1["cases"]) == len(d2["cases"])
        s = [gen_pair._snap_after(base, d, ops, p["auth"]) for d in p["w"]]
        f = [gen_pair._facts(d, p["info"]) for d in p["w"]]
        docs = [low_view(si, p["auth"], p["observer"], ops, fi).to_doc() for si, fi in zip(s, f)]
        assert docs[0] == docs[1], p["id"]  # low-equivalence BEFORE any variant runs
        if not p["aa"]:
            assert (s[0] != s[1]) or d1["edges"] != d2["edges"] or d1["cases"] != d2["cases"] or d1["high"] != d2["high"]
    assert errors == 0
    assert made > 1500 and {"F", "E", "L", "D", "C", "G"} <= kinds, (made, skipped, kinds)


def test_aa_pairs_run_identical_worlds():
    p, _ = gen_pair.draw(3, 0, aa=True)
    assert p["w"][0] == p["w"][1] and p["aa"]


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
def test_auth_perturbation_always_valid_and_deterministic(dom):
    ops, au, _g = gen_pair.load(dom)
    for s in range(300):
        a = gen_auth.perturb(random.Random(s), ops, au, str(s))
        validate_strict(a, ops)
        assert a == gen_auth.perturb(random.Random(s), ops, au, str(s))
        assert len(a["principals"]) >= len(au["principals"]) + 2


def test_every_variation_kind_is_drawn_per_domain():
    seen = {(d, k) for d in gen_pair.DOMAINS for k in "FEDCGL"
            if any(gen_pair.draw(9, i, kind=k, domain=d)[0] for i in range(40))}
    assert len(seen) == 12, seen
