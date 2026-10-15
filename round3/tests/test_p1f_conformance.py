"""Gate 4 seam conformance against the REGISTERED variants. Today both real variants predate P1f: their deploy() takes no
`external`, so g4_deploy must surface NotImplementedError("not implemented yet - G4") (the harness labels it `unsupported`, never
SUPPORTED). When a variant adopts the seam this test starts exercising it (G4 methods present and forms valid)."""
import pytest
from r3_shared.clock import LogicalClock
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.identity import IdentityProvider
from r3_shared.registry import load_variant
from r3_shared.variant import G4_MISSING, G4_METHODS, ExternalBinding, g4_call, g4_deploy
from r3_shared.world import WorldStore
from tests.fakes.fake_variant import FakeVariant


def _binding(tmp_path):
    systems = load_systems("manufacturing")
    return ExternalBinding(systems, {}, {}, ObservationClient(str(tmp_path), "k", systems), systems["window"])


@pytest.mark.parametrize("name", ["paladin", "conventional"])
def test_real_variant_adopts_the_seam_or_reports_not_implemented_g4(name, tmp_path):
    try:
        v = load_variant(name)
    except NotImplementedError as exc:
        assert "not implemented yet" in str(exc)
        return
    clock, idp, store = LogicalClock(), IdentityProvider("secret-secret"), WorldStore(tmp_path / "w.db")
    from r3_shared.authspec import load_auth_spec
    from r3_shared.opsspec import load_ops_spec
    try:
        dep = g4_deploy(v, "manufacturing", store.handle_factory(), idp.verifier(), load_ops_spec("manufacturing"),
                        load_auth_spec("manufacturing"), clock, external=_binding(tmp_path))
    except NotImplementedError as exc:
        assert str(exc) == G4_MISSING
        return
    for m in G4_METHODS:
        assert callable(getattr(dep, m)), f"{name}: Deployment lacks {m}"
    assert g4_call(dep, "outcome", "no-such-request").status == "INVALID"


def test_g4_deploy_reports_missing_seam_for_a_legacy_deploy_signature(tmp_path):
    class Legacy:
        def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
            raise AssertionError("must not be called")
    with pytest.raises(NotImplementedError, match="not implemented yet - G4"):
        g4_deploy(Legacy(), "manufacturing", None, None, {}, {}, None, external=_binding(tmp_path))


def test_g4_deploy_passes_external_through_to_a_conforming_variant(tmp_path):
    clock, idp, store = LogicalClock(), IdentityProvider("secret-secret"), WorldStore(tmp_path / "w.db")
    b = _binding(tmp_path)
    dep = g4_deploy(FakeVariant(), "manufacturing", store.handle_factory(), idp.verifier(), {}, {}, clock, external=b)
    assert dep.external is b
    assert g4_call(dep, "dispatch_pending").body == {"submitted": 0}


def test_g4_call_rejects_non_g4_names_and_missing_methods():
    with pytest.raises(ValueError):
        g4_call(object(), "approve")
    for m in G4_METHODS:
        with pytest.raises(NotImplementedError, match="not implemented yet - G4"):
            g4_call(object(), m)
