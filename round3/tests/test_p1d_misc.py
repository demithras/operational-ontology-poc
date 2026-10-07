"""P1d: mutant names, Gate 2 protocol surface, registry conformance for the new methods."""
import pytest
from r3_shared import mutants
from r3_shared.registry import VARIANTS, load_variant
from r3_shared.variant import G2_METHODS, G2_MISSING, ReplayResult, Variant, g2_call
from tests.fakes.fake_variant import FakeDeployment, FakeVariant


def test_new_mutant_names_accepted_and_frozen():
    assert mutants.KNOWN["H24"] == ["non_attenuating_delegation", "stale_authority_cache", "revoke_commit_reorder", "expiry_inclusive"]
    assert mutants.KNOWN["H27"] == ["digest_omission", "fallback_to_current", "evidence_rebinding", "receipt_self_trust"]
    assert mutants.validate(mutants.KNOWN["H24"] + mutants.KNOWN["H27"]) == frozenset(mutants.KNOWN["H24"] + mutants.KNOWN["H27"])
    assert mutants.validate(["stale_authority_cache"]) and FakeVariant(["receipt_self_trust"]).mutants
    with pytest.raises(ValueError):
        mutants.validate(["expiry_exclusive"])  # known negative: near-miss name
    assert mutants.ALL == frozenset(n for v in mutants.KNOWN.values() for n in v)


def test_replay_result_shape():
    r = ReplayResult("VERIFIED", "ok", {"seq": 1}, {"d": b"x"})
    assert (r.status, r.envelope, r.artifacts) == ("VERIFIED", {"seq": 1}, {"d": b"x"})
    assert ReplayResult("UNRESOLVED", "no_anchor").artifacts == {}
    with pytest.raises(ValueError):
        ReplayResult("MAYBE", "x")


def test_g2_call_surfaces_not_implemented_for_missing_methods():
    class Old:  # an H23-era deployment
        pass
    for m in G2_METHODS:
        with pytest.raises(NotImplementedError, match="not implemented yet - G2"):
            g2_call(Old(), m)
    assert G2_MISSING == "not implemented yet - G2"
    with pytest.raises(ValueError):
        g2_call(Old(), "call_tool")
    assert all(callable(getattr(FakeDeployment, m)) for m in G2_METHODS) and callable(FakeDeployment.authority_state)


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_registered_variants_g2_surface_is_present_or_not_implemented(name):
    """Real variants are not required to have the Gate 2 methods until their builders land; a missing method must surface
    as NotImplementedError("not implemented yet - G2") through g2_call (never AttributeError, never a fake success)."""
    try:
        v = load_variant(name)
    except NotImplementedError as exc:
        assert "not implemented yet" in str(exc)
        return
    assert isinstance(v, Variant)
    cls = v.deployment_class
    for m in G2_METHODS:
        if callable(getattr(cls, m, None)):
            continue
        with pytest.raises(NotImplementedError, match="not implemented yet - G2"):
            g2_call(object.__new__(cls), m)
