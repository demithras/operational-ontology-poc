"""Level 1 (docs/experiment/spec/08_test_strategy.md): `opa test
--fail-on-empty` against contracts/policies/<version>/*.rego, via the
openpolicyagent/opa docker image — same "shell out to the reference CLI
tool's own test runner" pattern as tests/contracts/test_openfga_model.py.
Needs no running OPA SERVER (opa test is a standalone command); DOCKER_CONFIG
must be set per docs/experiment/briefs/common.md (macOS credsStore hang).

Phase 7 (docs/experiment/spec/07_versioning_and_replay.md): parametrized
over every contracts/policies/vN/ directory that actually has *_test.rego
files (v1 always; v2+ once migrations/v1_to_v2 etc. publish them) — a NEW
version's bundle must pass its OWN suite exactly like v1 always has, never
exempted just for being newer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES_ROOT = REPO_ROOT / "contracts" / "policies"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _versions_with_tests() -> list[str]:
    versions = []
    for child in sorted(POLICIES_ROOT.iterdir()):
        if child.is_dir() and any(child.glob("*_test.rego")):
            versions.append(child.name)
    return versions


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker not available in this environment")


@pytest.mark.parametrize("version", _versions_with_tests())
def test_opa_test_suite_passes_and_is_not_empty(version):
    policies_dir = POLICIES_ROOT / version
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{policies_dir}:/policies:ro",
            "openpolicyagent/opa:latest",
            "test", "/policies", "--fail-on-empty",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"opa test failed for {version} (exit {result.returncode}) — CI gate 'OPA test suite empty/fails' "
        f"(docs/experiment/spec/13_repository_contract.md):\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "PASS" in result.stdout
