"""Hypothesis profiles (dev / ci), import path, and a REAL small H20 run (subprocess) that the evaluator tests edit copies of."""
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
    """A tiny but REAL run (domain e2e suites only, 100 synthetic): real payload shapes; below the frozen sample, so not SUPPORTED."""
    root = tmp_path_factory.mktemp("h20small")
    cmd = [sys.executable, str(ROOT / "scripts/run_h20.py"), "--exp-id", "small", "--seed", "3", "--n-synth", "100", "--n-machine", "10",
           "--n-probe", "30", "--suite", "tests/domains/test_manufacturing_e2e.py", "--suite", "tests/domains/test_project_e2e.py",
           "--out-root", str(root)]
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
    """The small run, with its synthetic rows replicated (new shas) to the frozen minimum: the known-positive for the evaluator tests."""
    d = tmp_path_factory.mktemp("h20pos") / "pos"
    shutil.copytree(small_run, d)
    if (d / "verdict.json").exists():
        (d / "verdict.json").unlink()

    def amplify(p):
        rows = p["definitions"]
        out = list(rows)
        i = 0
        while len(out) < 3100:
            r = dict(rows[i % len(rows)])
            r["sha"] = f"{r['sha']}-copy{i}"
            out.append(r)
            i += 1
        p["definitions"] = out
        p["alias_invariance"]["definitions"] = max(p["alias_invariance"]["definitions"], 400)
    rewrite(d, "synthetic-resource-results.json", amplify)
    return d


@pytest.fixture()
def pos(positive_template, tmp_path):
    d = tmp_path / "ev"
    shutil.copytree(positive_template, d)
    return d
