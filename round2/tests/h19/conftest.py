"""Hypothesis profiles (dev / ci), import path for round2, shared fixtures for the H19 tests."""
import os
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
def env(tmp_path_factory):
    from eoo_h19.seed import Env
    e = Env(tmp_path_factory.mktemp("h19env"))
    yield e
    e.close()


@pytest.fixture(scope="session")
def scenarios():
    from eoo_h19.gen import generate
    return generate(1919, 120)[0]


@pytest.fixture(scope="session")
def small_run(tmp_path_factory):
    """A REAL (tiny) H19 run: real provenance, hashes and payload shapes; the evaluator tests edit copies of it."""
    from eoo_h19 import run as runner
    root = tmp_path_factory.mktemp("h19small")
    runner.run(5, 120, root, "small", audit_n=12, mut_n=80, mut_audit_n=8, log=lambda m: None)
    return root / "small"
