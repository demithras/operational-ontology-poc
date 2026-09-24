#!/usr/bin/env python3
"""experiments/exp-NNN/results/environment.json + contract-manifest.json
(docs/experiment/spec/13_repository_contract.md). Both are always
re-derived from live sources (git, host_load, the manifest builders) —
never hand-typed.

contract-manifest.json extends spec 13's example shape with a second,
top-level `baseline` block (services/baseline/manifest.py) alongside the
`ontology` block (services/decision_service/manifest.py) — both variants'
CURRENTLY-deployed contract versions/hashes, side by side, since this
experiment always runs both variants against the same live stack.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.common import host_load  # noqa: E402
from services.decision_service.manifest import build_manifest  # noqa: E402
from services.baseline.manifest import build_baseline_manifest  # noqa: E402


def _docker_compose_ps() -> list[dict]:
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        rows = []
        for line in result.stdout.strip().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return [{"name": r.get("Name"), "service": r.get("Service"), "state": r.get("State"), "health": r.get("Health")} for r in rows]
    except (OSError, subprocess.SubprocessError):
        return []


def gen_environment(results_dir: Path) -> dict:
    load = host_load.sample_host_load()
    git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    git_dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip())
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": git_commit,
        "git_working_tree_dirty": git_dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": load.cpu_count,
        "host_load_sample": load.to_dict(),
        "docker_compose_services": _docker_compose_ps(),
    }
    (results_dir / "environment.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return doc


def gen_contract_manifest(results_dir: Path) -> dict:
    ontology = build_manifest()
    baseline = build_baseline_manifest()
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ontology": ontology,
        "baseline": baseline,
        "note": (
            "Both blocks are derived from the SAME live "
            "contracts/manifests/deployed_version.json (services/baseline/manifest.py's own docstring: "
            "'both variants version-pin from the exact same live file') — ontology additionally carries "
            "ontology/shapes/projections/reconciliation, which the baseline variant has no equivalent of "
            "(no RDF semantic core)."
        ),
    }
    (results_dir / "contract-manifest.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return doc


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    gen_environment(results_dir)
    gen_contract_manifest(results_dir)
    print(f"wrote environment.json + contract-manifest.json to {results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
