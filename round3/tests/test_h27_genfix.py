"""g2-genfix: H27 generators (base histories, tamper corpus) never raise on empty choices."""
import random

import pytest

from r3_harness.h27 import corpus, layout, tamper
from r3_shared.anchor import start_anchor
from r3_shared.histstore import TamperView
from tests.fakes import fake_h27


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("h27gf")
    ap = start_anchor(d / "anchor", d / "sock")
    try:
        var = fake_h27.load("fake-h27-honest")
        yield {"var": var, "anchor": ap.client(), "dir": d}
    finally:
        ap.close()


def test_base_histories_for_seeds_0_to_9_build_without_error(world):
    for seed in range(10):
        bases = corpus.build_bases(world["var"], world["anchor"], str(world["dir"] / f"w{seed}"), seed, 1, (5, 8))
        assert len(bases) == 2 and all(b.n >= 1 for b in bases)


def test_tamper_plans_over_many_seeds_never_raise(world):
    errs, total = [], 0
    for seed in range(4):
        bases = corpus.build_bases(world["var"], world["anchor"], str(world["dir"] / f"p{seed}"), seed, 2, (5, 8), tag="pb")
        pl = corpus.plan(random.Random(seed), 40, len(bases))
        try:
            total += sum(1 for _ in corpus.run_plan(world["var"], world["anchor"], bases, pl,
                                                    str(world["dir"] / f"pr{seed}"), seed))
        except Exception as exc:  # noqa: BLE001
            errs.append((seed, f"{type(exc).__name__}: {exc}"))
    assert not errs, errs
    assert total == 160


def test_t1_envelope_branch_with_no_flippable_leaf_is_a_noop_not_an_error(world, monkeypatch):
    """Known-negative for the old rng.choice([]) crash: force the envelope branch with an envelope that has no leaves."""
    base = corpus.build_bases(world["var"], world["anchor"], str(world["dir"] / "t1"), 3, 1, (5, 8), tag="t1b")[0]
    _, h = base.copy_to(str(world["dir"] / "t1c"))
    view = TamperView(h)
    monkeypatch.setattr(tamper, "_leaves", lambda obj: [])

    class R(random.Random):
        def random(self):  # force the `else` (envelope) branch of t1
            return 0.9
    assert tamper.t1(view, base, R(1), {"flags": set()}) is False
