"""Level 1 (docs/experiment/spec/08_test_strategy.md): `opa test
--fail-on-empty` against contracts/policies/v1/*.rego, via the
openpolicyagent/opa docker image — same "shell out to the reference CLI
tool's own test runner" pattern as tests/contracts/test_openfga_model.py.
Needs no running OPA SERVER (opa test is a standalone command); DOCKER_CONFIG
must be set per docs/experiment/briefs/common.md (macOS credsStore hang).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES_DIR = REPO_ROOT / "contracts" / "policies" / "v1"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker not available in this environment")


def test_opa_test_suite_passes_and_is_not_empty():
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{POLICIES_DIR}:/policies:ro",
            "openpolicyagent/opa:latest",
            "test", "/policies", "--fail-on-empty",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"opa test failed (exit {result.returncode}) — CI gate 'OPA test suite empty/fails' "
        f"(docs/experiment/spec/13_repository_contract.md):\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "PASS" in result.stdout
