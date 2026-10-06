import pytest
from r3_shared import mutants
from r3_shared.registry import load_variant
from tests.fakes.fake_variant import FakeVariant


def test_known_and_validate():
    assert mutants.KNOWN["H23"] == ["identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure"]
    assert mutants.ALL == frozenset(mutants.KNOWN["H23"])
    assert mutants.validate(["backstop_bypass"]) == frozenset({"backstop_bypass"})
    assert mutants.validate(()) == frozenset()
    with pytest.raises(ValueError):
        mutants.validate(["nope"])
    with pytest.raises(ValueError):
        mutants.validate("backstop_bypass")


def test_variant_constructor_validates():
    assert FakeVariant(["tool_overexposure"]).mutants == frozenset({"tool_overexposure"})
    with pytest.raises(ValueError):
        FakeVariant(["bogus"])


def test_load_variant_unknown_name_still_keyerror():
    with pytest.raises(KeyError):
        load_variant("fake", mutants=["backstop_bypass"])
