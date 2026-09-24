#!/usr/bin/env python3
"""F28 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"ontology migration incompatible -> CI/replay -> build fails") — the
compat-CI script docs/experiment/spec/07_versioning_and_replay.md's
"Compatibility CI" item 6 requires ("migration fixture tests").

Rule (kept deliberately simple and STRUCTURAL, never trusting a self-
reported claim): for every contracts/<kind>/vN/ directory that has real
content (N >= 2), a corresponding migrations/v{N-1}_to_v{N}/ directory must
exist, be non-empty, and contain at least one migration script (a *.py
file). Where that migration directory also publishes a migration.json
fixture (this repo's own convention — see migrations/v1_to_v2/migration.json),
its `migration_script`/`deploy_script` paths are verified to actually exist
on disk too — a JSON file that CLAIMS "replay_verified": true is not itself
evidence; make test-replay (tests/replay/) is the actual replay-corpus
proof, run independently.

Run directly:

    .venv/bin/python scripts/compat_check.py

Exits 1 (and prints every violation) on any breaking change lacking its
migration — never exits 0 while a violation exists (common.md "never fake
success").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

KINDS = ("ontology", "shapes", "actions", "policies", "projections", "identity", "authorization", "reconciliation")


def _has_real_content(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(p.is_file() and p.name != ".gitkeep" for p in directory.iterdir())


def _version_dirs_with_content(kind_root: Path) -> list[int]:
    """Returns the sorted list of integer version numbers ("v3" -> 3) that
    have real published content under kind_root."""
    versions = []
    if not kind_root.is_dir():
        return versions
    for child in sorted(kind_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if not (name.startswith("v") and name[1:].isdigit()):
            continue
        if _has_real_content(child):
            versions.append(int(name[1:]))
    return sorted(versions)


def run_compat_check(contracts_root: Path, migrations_root: Path) -> list[str]:
    violations: list[str] = []
    for kind in KINDS:
        kind_root = contracts_root / kind
        versions = _version_dirs_with_content(kind_root)
        for v in versions:
            if v < 2:
                continue  # v1 (or any v0) is the baseline — nothing to migrate FROM.
            prev = v - 1
            migration_dir = migrations_root / f"v{prev}_to_v{v}"
            if not migration_dir.is_dir():
                violations.append(
                    f"{kind}/v{v} exists but migrations/v{prev}_to_v{v}/ does not (F28: breaking change without migration)"
                )
                continue
            scripts = [p for p in migration_dir.glob("*.py") if p.is_file()]
            if not scripts:
                violations.append(
                    f"migrations/v{prev}_to_v{v}/ exists but contains no migration script (*.py) for {kind}/v{v}"
                )
            fixture = migration_dir / "migration.json"
            if fixture.exists():
                try:
                    data = json.loads(fixture.read_text())
                except json.JSONDecodeError as exc:
                    violations.append(f"migrations/v{prev}_to_v{v}/migration.json is not valid JSON: {exc}")
                    continue
                for key in ("migration_script", "deploy_script"):
                    rel = data.get(key)
                    if not rel:
                        continue
                    if not (REPO_ROOT / rel).exists():
                        violations.append(
                            f"migrations/v{prev}_to_v{v}/migration.json's {key!r}={rel!r} does not exist on disk"
                        )
    return violations


def main() -> int:
    contracts_root = REPO_ROOT / "contracts"
    migrations_root = REPO_ROOT / "migrations"
    violations = run_compat_check(contracts_root, migrations_root)
    if violations:
        print("compat_check FAILED — breaking change(s) without migration coverage:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("compat_check OK — every published contract version >= 2 has a corresponding migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
