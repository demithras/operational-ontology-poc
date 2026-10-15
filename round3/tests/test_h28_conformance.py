"""C28-0..6 (ORACLE-AND-HARNESS-G4 s9). Against the REGISTERED variants these must FAIL (never skip) until the variants adopt the seam;
each check also passes on FakeHonest and fails on its known-negative fake."""
import pytest

from r3_harness.h28 import conformance as C
from r3_shared.registry import load_variant
from tests.fakes import fake_h28

REGISTERED = ("paladin", "conventional")


def real(name):
    def f(m):
        return load_variant(name, m)
    return f


def honest(m):
    return fake_h28.load("FakeHonest", m)


def neg(name):
    return lambda m: fake_h28.load(name, m)


def test_c28_0_oracle_isolation():
    assert C.c0_oracle_isolation() == []


SMALL = {"C28-1": dict(n=8), "C28-2": dict(n_points=300), "C28-3": dict(n=12), "C28-4": dict(per_prim=12), "C28-5": dict(n=10),
         "C28-6": dict(n=8)}


@pytest.mark.parametrize("cid", sorted(C.ALL))
def test_fake_honest_conforms(cid):
    assert C.ALL[cid](honest, **SMALL[cid]) == []


NEGATIVE = {"C28-1": "FakeLegacyWrite", "C28-2": "FakeAnyRowSuccess", "C28-3": "FakeRootCapToAdapter", "C28-4": "FakeConsumesArtefact",
            "C28-5": None, "C28-6": "FakeFreshCapRetry"}


@pytest.mark.parametrize("cid", sorted(k for k, v in NEGATIVE.items() if v))
def test_known_negative_fails(cid):
    assert C.ALL[cid](neg(NEGATIVE[cid]), **SMALL[cid]) != []


@pytest.mark.parametrize("cid", sorted(C.ALL))
@pytest.mark.parametrize("name", REGISTERED)
def test_registered_variant_conforms(name, cid):
    """EXPECTED TO FAIL until the variant lands (never skipped): the seam, outcome function, caveats, decide-before-dispatch,
    refusal order and crash redelivery are the variant's work."""
    try:
        load_variant(name)
    except NotImplementedError as exc:
        pytest.fail(f"{name}: {exc}")
    problems = C.ALL[cid](real(name), **SMALL[cid])
    assert problems == [], problems
