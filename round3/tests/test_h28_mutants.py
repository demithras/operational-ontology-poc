"""Every H28 mutant (P1f-9) at its real site in the reference fake is killed by its OWN class on the frozen-style subset, and the
clean build is 0 on that class (exact case ids; kill rule of PROT-H28 s9)."""
import tempfile

import pytest

from r3_harness.h28.factories import NamedFactory
from r3_harness.h28 import mutation
from r3_shared import mutants
from tests.fakes import fake_h28

_R = {}


def proof():
    if "r" not in _R:
        _R["r"] = mutation.prove(NamedFactory("fake-FakeHonest"), "fake", 2811, tempfile.mkdtemp(prefix="h28m"), per_prim=6, extra=24)
    return _R["r"]


@pytest.mark.parametrize("name", mutants.KNOWN["H28"])
def test_mutant_killed_by_own_class(name):
    r = proof()[name]
    assert r["own_class_count"] > 0 and r["case_ids"], r
    assert r["clean_count"] == 0 and r["killed"], r


def test_kill_rate_is_one_and_names_match_the_registry():
    r = proof()
    assert set(mutation.OWN_CLASS) == set(mutants.KNOWN["H28"])
    assert all(r[n]["killed"] for n in mutants.KNOWN["H28"])
    assert r["_subset"]["cases"] > 0


def test_a_clean_build_kills_nothing():
    """Known negative of the kill rule: the clean build is not 'killed' against itself (own count 0 -> not killed)."""
    from r3_harness.h28.mutation import _kill
    agg = {"unattributed_scope_rows": [], "classes": {}, "harness": {}}
    clean = {"agg": agg, "rows": [{"case": "x", "classes": {}, "detect": [1, 1]}]}
    assert _kill("adapter_success_trusted", clean, clean)["killed"] is False
