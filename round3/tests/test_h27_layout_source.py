"""HISTORY_LAYOUT is read from the Variant class OR the deployment class (real variants declare it on the deployment):
before the fix a deployment-declared layout was ignored and T9 was silently a no-op for BOTH real variants."""
import pytest

from r3_harness.h27 import case, corpus, tamper
from r3_shared.anchor import start_anchor
from tests.fakes import fake_h27


class DeploymentDeclares:
    """Variant class WITHOUT HISTORY_LAYOUT; the layout lives on the deployed object (as in paladin/conventional)."""
    audience = "fake"
    TEST_WORLD_WRITER = "fake-service"

    def __init__(self, inner):
        self.inner = inner

    def deploy(self, *a, **kw):
        dep = self.inner.deploy(*a, **kw)
        dep.HISTORY_LAYOUT = dict(fake_h27.FakeH27Variant.HISTORY_LAYOUT)
        return dep


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("h27lay")
    ap = start_anchor(d / "anchor", d / "sock")
    try:
        var = DeploymentDeclares(fake_h27.load("fake-h27-honest"))
        bases = corpus.build_bases(var, ap.client(), str(d / "w"), 7, 2, (10, 14))
        yield {"var": var, "anchor": ap.client(), "bases": bases, "dir": d}
    finally:
        ap.close()


def test_layout_declared_on_the_deployment_is_used(env):
    assert not hasattr(type(env["var"]), "HISTORY_LAYOUT")
    for b in env["bases"]:
        assert set(b.stream.layout) >= {"idempotency", "approval", "envelope"}


def test_t9_is_applied_not_silently_dropped_when_the_layout_is_on_the_deployment(env):
    r = case.run_case(env["bases"][0], env["var"], env["anchor"], str(env["dir"] / "c"), "t9", 3, ["T9"])
    assert r["applied"] == ["T9"] and "continuation" in r["flags"] and r["unsupported"] is None
    assert corpus.effective(r)
    assert "T9" in tamper.CLASSES
