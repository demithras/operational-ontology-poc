"""A6 known-negative fakes: each yields exactly its expected violation-class set and verdict through the real runner and
evaluator; FakeHonest is SUPPORTED on a small dev corpus ONLY through recorded dev minimum overrides (never registered)."""
import json
from pathlib import Path

import pytest

from r3_harness.h24 import evaluator
from r3_harness.h24.rows import VIOLATIONS
from r3_harness.h24.runner import run_variant
from tests.fakes.h24_fakes import load

ROUND3 = Path(__file__).resolve().parents[1]
TH = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
SEQS, RACES, MUT = 40, 90, (30, 45)
DEV = {"min_sequences": SEQS, "min_concurrent": 30}

# fake -> (expected violation classes seen on the dev corpus, verdict)
EXPECTED = {
    "fake-honest": (set(), "SUPPORTED"),
    "fake-amplifier": ({"scope_amplification", "forbidden_effect"}, "REJECTED"),
    "fake-stalecache": ({"post_boundary_effect"}, "REJECTED"),
    "fake-earlyack": ({"linearizability_violation", "authority_ack_without_commit"}, "REJECTED"),
    "fake-inclusiveexpiry": ({"post_boundary_effect"}, "REJECTED"),
    "fake-cyclegrant": ({"cycle_grant"}, "REJECTED"),
    "fake-serializer": ({"progress_loss"}, "INCONCLUSIVE"),  # safe only because it blocks: must NOT be SUPPORTED
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("h24fakes")
    out = {}
    for name in EXPECTED:
        d = root / "exp-h24-dev" / name
        run_variant(lambda m, n=name: load(n, m), name, d, "exp-h24-dev", 1, SEQS, RACES, MUT[0], MUT[1])
        out[name] = (d, evaluator.evaluate_variant(d, TH, name, **DEV))
    return out


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_fake_yields_exactly_its_class_set_and_verdict(runs, name):
    d, res = runs[name]
    seen = {k for k, v in res["metrics"]["class_counts"].items() if v and k in VIOLATIONS}
    want, verdict = EXPECTED[name]
    assert seen == want, (seen, res["reasons"])
    assert res["verdict"] == verdict, res["reasons"]


def test_fake_honest_is_supported_only_with_recorded_overrides_and_full_mutation_proof(runs):
    d, res = runs["fake-honest"]
    assert res["minimum_overrides"] == DEV and any(x.startswith("DEV ONLY") for x in res["reasons"])
    assert res["metrics"]["mutation_kill_rate"] == 1.0 and res["metrics"]["safe_progress_ratio"] == 1.0
    assert evaluator.evaluate_variant(d, TH, "fake-honest")["verdict"] == "INCONCLUSIVE"  # frozen minimums are far away
    mut = json.loads((d / "mutation-results.json").read_text())
    assert all(v["killed"] and v["killing_class"] and v["first_killing_case"] for v in mut.values())


def test_serializer_is_safe_but_loses_progress_and_is_never_supported(runs):
    _, res = runs["fake-serializer"]
    assert res["metrics"]["safe_progress_ratio"] < 1.0 and res["metrics"]["stale_or_forbidden_effects"] == 0
    assert any("unaffected-legit progress" in x for x in res["reasons"])


def test_mutants_that_the_fake_lacks_survive_never_skipped(tmp_path):
    from r3_harness.h24 import mutation
    from r3_harness.h23.corpus import load_specs
    res = mutation.prove(lambda m: load("fake-honest", ()), load_specs(), 10, 10, 1)  # the factory ignores the mutant
    assert set(res) == set(__import__("r3_shared.mutants", fromlist=["KNOWN"]).KNOWN["H24"])
    assert not any(v["killed"] for v in res.values())
