"""Hypothesis profiles (dev / ci), import path, and a REAL small H21 run (subprocess) that the evaluator tests edit copies of."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_SUPPRESS = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much, HealthCheck.large_base_example]
settings.register_profile("dev", max_examples=200, deadline=None, suppress_health_check=_SUPPRESS, database=None)
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, suppress_health_check=_SUPPRESS, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(scope="session")
def small_run(tmp_path_factory):
    """A tiny but REAL run: real payload shapes; below the frozen sample, so not SUPPORTED."""
    root = tmp_path_factory.mktemp("h21small")
    cmd = [sys.executable, str(ROOT / "scripts/run_h21.py"), "--exp-id", "small", "--seed", "3", "--n-cases", "300", "--n-engine", "100",
           "--n-mutant-cases", "200", "--n-fuzz", "20", "--out-root", str(root)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900, env={**os.environ, "HYPOTHESIS_PROFILE": "dev"})
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    return root / "small"


def rewrite(d: Path, fname: str, fn) -> None:
    """Edit the payload of one evidence record in place and re-seal its payload hash (so only the content changed)."""
    from eoo_exp.util import canon, sha_text
    rec = json.loads((d / fname).read_text())
    fn(rec["payload"])
    rec["payload_hash"] = sha_text(canon(rec["payload"]))
    (d / fname).write_text(json.dumps(rec, indent=1, sort_keys=True))


@pytest.fixture(scope="session")
def positive_template(small_run, tmp_path_factory):
    """The small run with its case-hash lists amplified to the frozen minimum: the known-positive for the evaluator tests."""
    d = tmp_path_factory.mktemp("h21pos") / "pos"
    shutil.copytree(small_run, d)
    if (d / "verdict.json").exists():
        (d / "verdict.json").unlink()

    def amplify(p):
        for dom in p["domains"].values():
            have = list(dom["case_sha256"])
            dom["case_sha256"] = have + [f"amp-{i}" for i in range(10100 - len(have))]
    rewrite(d, "security-differential.json", amplify)
    return d


@pytest.fixture()
def pos(positive_template, tmp_path):
    d = tmp_path / "ev"
    shutil.copytree(positive_template, d)
    return d


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """Both domains generated once: {domain: (ir, build dir, inventory, sdk, caps, surface)}."""
    from domains._pack import load_ir
    from eoo_toolchain import build, load_generated
    out = {}
    for dom in ("manufacturing", "project"):
        ir, d = load_ir(dom), tmp_path_factory.mktemp("h21gen" + dom)
        inv = build(ir, d)
        out[dom] = (ir, d, inv, *load_generated(d, inv["package"]))
    return out
