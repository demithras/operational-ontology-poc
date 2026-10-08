"""Generators never raise (seed sweep 0..1999) and produce what the spec promises (ORACLE-AND-HARNESS-G3 A2)."""
import random

import pytest

from r3_harness.h25 import gen_model
from r3_harness.h25.gen_case import run_case, run_nogov
from r3_harness.h25.gen_race import TYPES, run_race
from r3_oracle.const_static import static_errors
from r3_shared.governance import structural_signature, structurally_distinct
from tests.h25_util import fake


def test_model_instances_sweep_0_1999_never_raise_and_validate():
    n = 0
    for seed in range(2000):
        model, dom = gen_model.MODELS[seed % 3] if hasattr(gen_model, "MODELS") else ("hierarchical", "manufacturing"), None
        model = ("hierarchical", "collegial", "polycentric")[seed % 3]
        dom = gen_model.DOMAINS[(seed // 3) % 2]
        inst = gen_model.make_instance(model, dom, seed)
        assert not static_errors(inst["doc"], inst["auth"], inst["ops"])
        n += inst["redraws"]
    assert n < 2000 * 0.5  # re-draws are rare, counted, never raised


def test_invalid_and_valid_variants():
    for seed in range(300):
        inst = gen_model.make_instance(("hierarchical", "collegial", "polycentric")[seed % 3], gen_model.DOMAINS[seed % 2], seed)
        rng = random.Random(seed)
        bad, name = gen_model.invalid_doc(inst, rng)
        assert static_errors(bad, inst["auth"], inst["ops"]), name
        good = gen_model.valid_variant(inst, rng)
        assert not static_errors(good, inst["auth"], inst["ops"])


def test_fixture_models_pairwise_structurally_distinct():
    docs = [gen_model.fixture(m, "manufacturing") for m in ("hierarchical", "collegial", "polycentric")]
    for i in range(3):
        for j in range(i + 1, 3):
            assert structurally_distinct(docs[i], docs[j]), (structural_signature(docs[i]), structural_signature(docs[j]))


def test_case_sweep_never_raises():
    v = fake("fake-honest")
    for seed in range(2000):
        r = run_case(v, seed, seed % 97)
        assert r["calls"] and not (set(r["classes"]) - {"ok", "race_refusal_ok"}), (seed, r["classes"])


@pytest.mark.parametrize("rtype", TYPES)
def test_race_sweep_never_raises(rtype):
    v = fake("fake-honest")
    for seed in range(40):
        r = run_race(v, seed, seed, rtype)
        assert not (set(r["classes"]) - {"ok", "race_refusal_ok"}), (rtype, seed, r["classes"])


def test_nogov_sweep():
    v = fake("fake-honest")
    for i in range(30):
        r = run_nogov(v, 1, i)
        assert set(r["classes"]) <= {"ok"} and "execute:INVALID:no_governance" in r["tags"]


def test_cases_are_deterministic_and_unique():
    v = fake("fake-honest")
    a = [run_case(v, 5, i)["digest"] for i in range(20)]
    b = [run_case(v, 5, i)["digest"] for i in range(20)]
    assert a == b and len(set(a)) == 20
