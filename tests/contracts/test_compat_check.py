"""F28 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"ontology migration incompatible -> CI/replay -> build fails") —
scripts/compat_check.py, exercised both against the REAL repo tree
(positive case: every published vN >= 2 has migration coverage) and a
synthetic known-bad tree (negative case: a version published with no
migration must be CAUGHT, not silently accepted).
"""

from __future__ import annotations

from pathlib import Path

from scripts.compat_check import run_compat_check

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_repo_tree_has_no_compat_violations():
    violations = run_compat_check(REPO_ROOT / "contracts", REPO_ROOT / "migrations")
    assert violations == [], f"real contracts tree has uncovered breaking change(s): {violations}"


def test_known_bad_version_without_migration_is_caught(tmp_path):
    contracts = tmp_path / "contracts"
    migrations = tmp_path / "migrations"
    (contracts / "ontology" / "v1").mkdir(parents=True)
    (contracts / "ontology" / "v1" / "fac-core.ttl").write_text("# v1")
    # v9 published with NO migrations/v8_to_v9/ directory at all — the
    # canonical F28 shape ("ontology migration incompatible").
    (contracts / "ontology" / "v9").mkdir(parents=True)
    (contracts / "ontology" / "v9" / "fac-core.ttl").write_text("# v9, breaking")

    violations = run_compat_check(contracts, migrations)
    assert any("ontology/v9" in v and "migrations/v8_to_v9" in v for v in violations), violations


def test_known_bad_migration_dir_present_but_empty_is_caught(tmp_path):
    contracts = tmp_path / "contracts"
    migrations = tmp_path / "migrations"
    (contracts / "ontology" / "v1").mkdir(parents=True)
    (contracts / "ontology" / "v1" / "fac-core.ttl").write_text("# v1")
    (contracts / "ontology" / "v2").mkdir(parents=True)
    (contracts / "ontology" / "v2" / "fac-core.ttl").write_text("# v2, breaking")
    # A migration directory exists (an operator remembered to create it)
    # but contains no actual script — still not real migration coverage.
    (migrations / "v1_to_v2").mkdir(parents=True)
    (migrations / "v1_to_v2" / "README.md").write_text("TODO: write the migration")

    violations = run_compat_check(contracts, migrations)
    assert any("contains no migration script" in v for v in violations), violations


def test_known_bad_migration_json_points_at_missing_script_is_caught(tmp_path):
    contracts = tmp_path / "contracts"
    migrations = tmp_path / "migrations"
    (contracts / "ontology" / "v1").mkdir(parents=True)
    (contracts / "ontology" / "v1" / "fac-core.ttl").write_text("# v1")
    (contracts / "ontology" / "v2").mkdir(parents=True)
    (contracts / "ontology" / "v2" / "fac-core.ttl").write_text("# v2, breaking")
    mig_dir = migrations / "v1_to_v2"
    mig_dir.mkdir(parents=True)
    (mig_dir / "migrate.py").write_text("# real script, present")
    import json

    (mig_dir / "migration.json").write_text(json.dumps({
        # A real, existing script in THIS repo (isolates the check to the
        # deploy_script field below).
        "migration_script": "migrations/v1_to_v2/migrate_rdf.py",
        # A path that does not exist anywhere in THIS repo — the fixture
        # lies about a deploy script it never actually shipped.
        "deploy_script": "migrations/v1_to_v2/does_not_exist.py",
    }))

    violations = run_compat_check(contracts, migrations)
    assert any("does_not_exist.py" in v for v in violations), violations
