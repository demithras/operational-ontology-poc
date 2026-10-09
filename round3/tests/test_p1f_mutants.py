"""P1f-9: the KNOWN mutant names for H28, exactly as frozen; activated only through a variant constructor."""
import pytest
from r3_shared import mutants
from tests.fakes.fake_variant import FakeVariant

FROZEN = ["adapter_success_trusted", "credential_scope_broadened", "policy_gate_in_adapter", "idempotency_disabled",
          "observation_coupled", "divergence_rewritten"]


def test_h28_known_exact_and_unique_across_gates():
    assert mutants.KNOWN["H28"] == FROZEN
    assert set(FROZEN) <= mutants.ALL
    others = [n for k, v in mutants.KNOWN.items() if k != "H28" for n in v]
    assert not set(FROZEN) & set(others)


@pytest.mark.parametrize("name", FROZEN)
def test_each_name_validates_and_constructs(name):
    assert mutants.validate([name]) == frozenset({name})
    assert FakeVariant([name]).mutants == frozenset({name})


def test_near_miss_names_are_refused():
    for bad in ("adapter_success_trust", "Adapter_Success_Trusted", "divergence_rewrite", "policy_gate_in_adapters"):
        with pytest.raises(ValueError):
            mutants.validate([bad])
