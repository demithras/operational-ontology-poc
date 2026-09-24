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


def _load_migration_fixtures(migrations_root: Path) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Every migrations/*/migration.json on disk, parsed once. Returns
    (fixtures, parse_violations) — a malformed fixture is reported as a
    violation but does not stop the scan of the others."""
    fixtures: list[tuple[Path, dict]] = []
    violations: list[str] = []
    if not migrations_root.is_dir():
        return fixtures, violations
    for mig_dir in sorted(migrations_root.iterdir()):
        fixture = mig_dir / "migration.json"
        if not fixture.is_file():
            continue
        try:
            data = json.loads(fixture.read_text())
        except json.JSONDecodeError as exc:
            violations.append(f"{fixture.relative_to(REPO_ROOT) if fixture.is_relative_to(REPO_ROOT) else fixture} is not valid JSON: {exc}")
            continue
        fixtures.append((mig_dir, data))
        for key in ("migration_script", "deploy_script"):
            rel = data.get(key)
            if rel and not (REPO_ROOT / rel).exists():
                violations.append(f"{mig_dir.name}/migration.json's {key!r}={rel!r} does not exist on disk")
    return fixtures, violations


def run_compat_check(contracts_root: Path, migrations_root: Path) -> list[str]:
    """Kind-and-version-aware (not just version-NUMBER-aware): a
    contracts/<kind>/vN/ with real content (N >= 2) is covered if EITHER
    (a) some migrations/*/migration.json explicitly declares `kind` in its
    "kinds_changed" list AND "to_version" == "vN" (the precise claim —
    multiple kinds can share one migrations/ directory, e.g. this repo's
    migrations/v2_to_v3/ covers both `actions` reaching v3 AND
    `authorization` reaching v2 in the SAME deploy), OR (b) as a fallback
    for a kind that publishes no migration.json at all, a
    migrations/v{N-1}_to_v{N}/ directory NAMED BY THAT EXACT NUMBER exists
    with at least one script — never satisfied merely because SOME
    same-numbered directory happens to exist for an unrelated kind."""
    violations: list[str] = []
    fixtures, fixture_violations = _load_migration_fixtures(migrations_root)
    violations.extend(fixture_violations)

    declared_coverage: set[tuple[str, str]] = set()
    for mig_dir, data in fixtures:
        # `kind_versions` (kind -> its OWN target version) is the precise
        # form — required whenever a single migrations/ directory covers
        # kinds that reach DIFFERENT version numbers in the same deploy
        # (this repo's migrations/v2_to_v3/: actions -> v3, authorization ->
        # v2, per-kind independent numbering). Falls back to pairing every
        # kinds_changed entry with the single top-level `to_version` for
        # fixtures that don't need the distinction (migrations/v1_to_v2/:
        # every listed kind reaches v2 together).
        kind_versions = data.get("kind_versions")
        if kind_versions:
            for kind, version in kind_versions.items():
                declared_coverage.add((kind, version))
        else:
            to_version = data.get("to_version")
            for kind in data.get("kinds_changed", []):
                if to_version:
                    declared_coverage.add((kind, to_version))

    for kind in KINDS:
        kind_root = contracts_root / kind
        versions = _version_dirs_with_content(kind_root)
        for v in versions:
            if v < 2:
                continue  # v1 (or any v0) is the baseline — nothing to migrate FROM.
            version_str = f"v{v}"
            if (kind, version_str) in declared_coverage:
                continue
            prev = v - 1
            migration_dir = migrations_root / f"v{prev}_to_v{v}"
            if not migration_dir.is_dir():
                violations.append(
                    f"{kind}/{version_str} exists but no migration declares kinds_changed containing {kind!r} "
                    f"at to_version {version_str!r}, and migrations/v{prev}_to_v{v}/ does not exist either "
                    f"(F28: breaking change without migration)"
                )
                continue
            scripts = [p for p in migration_dir.glob("*.py") if p.is_file()]
            if not scripts:
                violations.append(
                    f"migrations/v{prev}_to_v{v}/ exists but contains no migration script (*.py) for {kind}/{version_str}"
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
