"""Level 1 (docs/experiment/spec/08_test_strategy.md "OpenFGA tests" +
CI gate "OpenFGA model tests fail", docs/experiment/spec/13_repository_contract.md):
`fga model test` against contracts/authorization/<version>/{model.fga,tests.yaml},
via the openfga/cli docker image. Needs no running OpenFGA SERVER — the CLI
spins up its own in-memory instance for `model test`. DOCKER_CONFIG must be
set per docs/experiment/briefs/common.md (macOS credsStore hang).

Phase 7 (docs/experiment/spec/07_versioning_and_replay.md): parametrized
over every contracts/authorization/vN/ directory that has a tests.yaml —
v1 always; v2 once migrations/v2_to_v3 publishes it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_ROOT = REPO_ROOT / "contracts" / "authorization"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _versions_with_tests() -> list[str]:
    return [c.name for c in sorted(AUTH_ROOT.iterdir()) if c.is_dir() and (c / "tests.yaml").exists()]


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker not available in this environment")


@pytest.mark.parametrize("version", _versions_with_tests())
def test_fga_model_test_suite_passes(version):
    auth_dir = AUTH_ROOT / version
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{auth_dir}:/app:ro", "openfga/cli:latest", "model", "test", "--tests", "/app/tests.yaml"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"fga model test failed for {version} (exit {result.returncode}) — CI gate 'OpenFGA model tests fail' "
        f"(docs/experiment/spec/13_repository_contract.md):\n{result.stdout}\n{result.stderr}"
    )
    # The `fga` CLI writes its "# Test Summary #" block to STDERR, not
    # stdout (verified empirically) — search both rather than assume.
    combined = result.stdout + result.stderr
    match = re.search(r"Tests (\d+)/(\d+) passing", combined)
    assert match is not None, f"could not parse test summary from:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    passed, total = int(match.group(1)), int(match.group(2))
    assert total > 0, "OpenFGA model test suite must not be empty"
    assert passed == total, f"{passed}/{total} fga model tests passed"
