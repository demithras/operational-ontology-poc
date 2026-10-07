"""E-7: a deploy that raises over history content is recorded as `deploy_crash` (never a detection/acceptance, never
SUPPORTED); the run continues and leaks no handles."""
import os

import pytest

from r3_harness.h27 import analyze, case, corpus, tamper
from r3_shared.anchor import start_anchor
from tests.fakes import fake_h27


class RaisingOnTamper:
    """Wraps the honest fake: deploy raises while `armed` (the harness arms it for tampered cases only)."""
    audience = "fake"
    TEST_WORLD_WRITER = "fake-service"
    HISTORY_LAYOUT = fake_h27.FakeH27Variant.HISTORY_LAYOUT

    def __init__(self, inner):
        self.inner, self.armed, self.raised = inner, False, 0

    def deploy(self, *a, **kw):
        if self.armed:
            self.raised += 1
            raise ValueError("edge e-3-2: unknown principal researcher-2~")  # the p12 H27-A shape
        return self.inner.deploy(*a, **kw)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("h27dc")
    ap = start_anchor(d / "anchor", d / "sock")
    var = fake_h27.load("fake-h27-honest")
    bases = corpus.build_bases(var, ap.client(), str(d / "w"), 7, 2, (10, 14))
    yield {"var": var, "anchor": ap.client(), "bases": bases, "dir": d}
    ap.close()


def test_deploy_exception_is_classified_deploy_crash_and_the_run_continues(env):
    v = RaisingOnTamper(env["var"])
    cdir = str(env["dir"] / "c-crash")
    v.armed = True
    r = case.run_case(env["bases"][0], v, env["anchor"], cdir, "t-crash", 5, [tamper.SINGLE[0]])
    assert r["classes_hit"] == ["deploy_crash"] and "unknown principal" in r["deploy_error"] and v.raised == 1
    assert r["replays"] == [] and not os.path.exists(cdir)
    assert "tamper_accepted" not in r["classes_hit"]
    v.armed = False  # the run continues: the next case on the same variant is measured normally
    r2 = case.run_case(env["bases"][0], v, env["anchor"], str(env["dir"] / "c-ok"), "t-ok", 6, [tamper.SINGLE[0]])
    assert "deploy_crash" not in r2["classes_hit"] and r2["replays"]


def test_deploy_crash_is_counted_by_analyze_and_blocks_a_sufficient_sample(env, tmp_path):
    import json
    rec = {"case": "x", "base": "b", "domain": "manufacturing", "classes": ["T1"], "applied": [], "flags": [],
           "definite": [], "indeterminate": [], "replays": [], "classes_hit": ["deploy_crash"]}
    (tmp_path / "tamper-mutation-results.json").write_text(json.dumps({"cases": [rec]}))
    (tmp_path / "historical-replay.json").write_text(json.dumps({"controls": [{**rec, "classes_hit": ["deploy_crash"]}]}))
    a = analyze.analyze(tmp_path)
    assert a["deploy_crashes"] == 2 and a["accepted"] == 0
