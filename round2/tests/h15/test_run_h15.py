"""The Phase 3 harness itself: determinism of the fixed-seed corpus, counterexample capture/shrinking, the sidecar audit's
ability to fail, the CLI's immutability rule and a tiny end-to-end run (schema-valid evidence, verdict derivable)."""
import json
import subprocess
import sys

import jsonschema
import pytest

import eoo_openpona as op
import eoo_openpona.ctx as ctx
from eoo_h15 import corpus, sidecar
from eoo_h15.evaluate import evaluate
from eoo_h15.genloop import GenLoop
from eoo_h15.evidence import REQUIRED

from openpona_util import ROOT, load


def _gen(n, seed=15, loop=None):
    loop = loop or GenLoop(log=open("/dev/null", "w"))
    corpus.generate(n, seed, loop)
    return loop


def test_fixed_seed_gives_the_same_corpus():
    a, b, c = _gen(25), _gen(25), _gen(25, seed=16)
    assert a.ch.result() == b.ch.result()
    assert a.ch.result()["corpus_sha256"] != c.ch.result()["corpus_sha256"]
    assert a.ch.n == 25


def test_clean_compilers_have_no_failures_on_a_small_corpus():
    loop = _gen(40)
    for s in ("openpona", "dsl"):
        assert loop.s[s]["failed"] == 0 and loop.s[s]["ok"] == 40


def test_counterexamples_are_captured_and_shrunk(monkeypatch):
    monkeypatch.setattr(ctx._C, "card", lambda self, a, side: {"min": 0, "max": "*"})  # known defect: cardinality dropped
    loop = _gen(60)
    s = loop.s["openpona"]
    assert s["failed"] > 0 and s["failures_by_ir_path"] and s["first_failures"]
    shrunk = loop.shrink(15)["openpona"]
    assert shrunk and all(x["minimal"] is not None for x in shrunk[:3])
    small = shrunk[0]["minimal"]
    assert len(json.dumps(small)) < len(json.dumps(s["first_failures"][0]["package"]))  # shrinking made it smaller
    assert loop.s["dsl"]["failed"] == 0  # the defect is in the OpenPona compiler only


def test_sidecar_audit_can_fail(monkeypatch):
    """Known-negative: a compiler that takes 'required' from the record (atom length parity) is an indispensable sidecar."""
    ir = load("tests/h15/openpona_coverage_ir.json")
    text, rec = op.render(ir)
    assert sidecar.audit_package(ir, text, rec)["alpha"]["ok"] and sidecar.audit_package(ir, text, rec)["shape"]["ok"]
    orig = ctx._C.one

    def sniffing(self, a, f, required=True):
        if f == "required":
            return len(self.rec.get(f"L{self.d.decls[a].line}.a1", "")) % 2 == 0
        return orig(self, a, f, required)
    monkeypatch.setattr(ctx._C, "one", sniffing)
    got = sidecar.audit_package(ir, text, rec)
    assert not (got["alpha"]["ok"] and got["shape"]["ok"]), "the audit did not notice structure read from the record"
    assert any(f["category"] for f in got["alpha"]["findings"] + got["shape"]["findings"])


@pytest.fixture(scope="module")
def tiny_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp")
    cmd = [sys.executable, str(ROOT / "scripts/run_h15.py"), "--exp-id", "exp-tiny", "--seed", "15", "--n", "12", "--out-root", str(root)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return root / "exp-tiny", r, cmd


def test_cli_run_writes_six_schema_valid_records(tiny_run):
    d, r, _ = tiny_run
    assert r.returncode == 0, r.stderr[-2000:]
    schema = json.loads((ROOT / "schemas/evidence-record.schema.json").read_text())
    for f in REQUIRED:
        rec = json.loads((d / f).read_text())
        jsonschema.validate(rec, schema)
        assert rec["git_commit"] and rec["protocol_freeze_hash"] and rec["seed"] == 15 and rec["harness_sha256"]
        assert rec["candidate_combined_sha256"] and rec["gate0_combined_sha256"] and rec["openpona_pin"]["commit"] == "97a9b9e"


def test_cli_refuses_to_overwrite(tiny_run):
    d, r, cmd = tiny_run
    assert d.exists()
    again = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert again.returncode == 2 and "REFUSED" in again.stderr


def test_tiny_run_is_inconclusive_not_supported(tiny_run):
    d, _, _ = tiny_run
    v = evaluate(d)
    assert v["verdict"] == "INCONCLUSIVE" and v["problems"] == [] and v["common"]["protocol_valid"] is True
    assert v["numbers"]["generated_valid_cases"] == 12


def _load_module_with_literals(tmp_path, name):
    import importlib.util
    f = tmp_path / f"{name}.py"
    f.write_text("X = [" + ", ".join(f"'lit{i}zq'" for i in range(300)) + ", " + ", ".join(str(70000 + i) for i in range(50)) + "]\n")
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return name


def _unisolated_sample():
    """30 packages from the same fixed seed WITHOUT the isolation (what plain Hypothesis does)."""
    import hypothesis.internal.conjecture.providers as prov
    from hypothesis import HealthCheck, Phase, given, seed, settings
    from eoo_ir.strategies import valid_packages
    out = []

    @seed(15)
    @settings(max_examples=30, database=None, deadline=None, phases=[Phase.generate], suppress_health_check=list(HealthCheck))
    @given(valid_packages())
    def f(p):
        out.append(json.dumps(p, sort_keys=True))
    prov.CONSTANTS_CACHE.cache.clear()
    f()
    return out


def test_corpus_does_not_depend_on_which_project_modules_are_loaded(tmp_path):
    """Hypothesis mixes literals of every loaded local module into generated values; the corpus must not (isolation.py).
    Known negative: without the isolation the same seed gives a different corpus once an extra module is loaded."""
    before, raw_before = _gen(30).ch.result()["corpus_sha256"], _unisolated_sample()
    name = _load_module_with_literals(tmp_path, "zz_extra_literals")
    try:
        after, raw_after = _gen(30).ch.result()["corpus_sha256"], _unisolated_sample()
    finally:
        sys.modules.pop(name, None)
    assert before == after, "isolated generation changed when an unrelated module was loaded"
    assert raw_before != raw_after, "the test has no teeth: plain Hypothesis ignored the extra module"
