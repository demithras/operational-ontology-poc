import pytest
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.registry import VARIANTS, load_variant
from r3_shared.variant import CallResult, Deployment, Variant
from r3_shared.world import WorldStore, diff
from tests.fakes.fake_variant import FakeVariant


def test_fake_variant_end_to_end_effect_measured_from_world(tmp_path):
    clock, idp, store = LogicalClock(), IdentityProvider("secret-secret"), WorldStore(tmp_path / "w.db")
    fv = FakeVariant()
    assert isinstance(fv, Variant)
    dep = fv.deploy("manufacturing", store.handle_factory(), idp.verifier(), {}, {}, clock)
    assert isinstance(dep, Deployment)
    tok = idp.issue("alice", "fake", 10, clock)
    reader = store.reader()
    before = reader.snapshot()
    assert dep.call_tool(tok, "put", {"type": "Part", "key": "P1"}).status == "OK"
    assert [e["kind"] for e in diff(before, reader.snapshot())] == ["create"]
    before = reader.snapshot()
    assert dep.direct("garbage", "put", {"type": "Part", "key": "P2"}).status == "DENIED"
    assert diff(before, reader.snapshot()) == []
    dep.crash()
    assert dep.direct(tok, "put", {"type": "Part", "key": "P3"}).status == "UNAVAILABLE"
    dep.restart()
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"] == {"by": "alice"}


def test_callresult_rejects_bad_status():
    with pytest.raises(ValueError):
        CallResult("MAYBE")


def test_registry_lazy_and_never_contains_fake():
    assert set(VARIANTS) == {"paladin", "conventional"}
    assert "fake" not in VARIANTS and not any("fake" in v for v in VARIANTS.values())
    with pytest.raises(KeyError):
        load_variant("fake")
    for n in ("paladin", "conventional"):
        try:
            v = load_variant(n)  # built (P2): a real Variant
        except NotImplementedError as exc:  # not built yet: must say so honestly
            assert "not implemented yet" in str(exc)
        else:
            assert v.name == n and isinstance(v, Variant)
