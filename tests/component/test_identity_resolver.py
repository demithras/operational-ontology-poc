"""Component tests for services/identity_resolver (docs/experiment/spec/08:
Level 2 "component tests", "resolver: exact, ambiguous -> quarantine,
source-id rename with the same mapping -> same canonical result
(metamorphic)").

The exact-match suite validates against seed/out/identity_truth.json (the
ground truth seed/load.py writes — docs/experiment/implementation-notes.md
Phase 2: "the ground truth to test the identity resolver against, including
the one intentional gap"). That file is generated (gitignored); if it
doesn't exist yet this test is explicitly SKIPPED with a reason (never
silently passed), same honesty pattern as tests/integration/conftest.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.identity_resolver.resolver import IdentityResolver, Quarantined, Resolved  # noqa: E402

IDENTITY_TRUTH_PATH = REPO_ROOT / "seed" / "out" / "identity_truth.json"


@pytest.fixture(scope="module")
def resolver() -> IdentityResolver:
    return IdentityResolver()


@pytest.fixture(scope="module")
def identity_truth() -> list[dict]:
    if not IDENTITY_TRUTH_PATH.exists():
        pytest.skip(f"{IDENTITY_TRUTH_PATH} not found — run 'make seed' first")
    return json.loads(IDENTITY_TRUTH_PATH.read_text())


# --- exact resolution against every seeded id ------------------------------


def test_resolves_every_seeded_id_to_its_ground_truth_canonical_id(
    resolver: IdentityResolver, identity_truth: list[dict]
):
    mismatches = []
    for entry in identity_truth:
        expected_canonical = entry["canonical_part_id"]
        for system in ("ERP", "MES", "WMS"):
            local_id = entry.get(system)
            if local_id is None:
                # Documented intentional gap (e.g. PX-0192 has no ERP row —
                # implementation-notes.md Phase 2 "ID collision, discovered
                # not assumed"). Nothing to resolve; not a resolver failure.
                continue
            result = resolver.resolve(system, local_id)
            if not isinstance(result, Resolved) or result.canonical_id != expected_canonical:
                mismatches.append((system, local_id, expected_canonical, result))

    assert not mismatches, f"{len(mismatches)} identity mismatches (showing up to 10): {mismatches[:10]}"


def test_canonical_fixture_part_resolves_on_all_three_systems(resolver: IdentityResolver):
    # seed/fixtures/canonical_incident.yaml's PX-17 — irregular ids that do
    # NOT follow the generated-index-v1 pattern (verifies the explicit
    # override rule, not just the regex rule).
    for system, local_id in [("ERP", "PART-00192"), ("MES", "COMP-A17"), ("WMS", "SKU-88429")]:
        result = resolver.resolve(system, local_id)
        assert isinstance(result, Resolved), f"{system}/{local_id} unexpectedly quarantined: {result}"
        assert result.canonical_id == "PX-17"
        assert result.rule_id == "canonical-fixture-v1"
        assert result.authority == "fixture-override"


def test_erp_id_192_belongs_only_to_the_fixture_part_not_the_generated_one(resolver: IdentityResolver):
    # The documented collision: PART-00192 syntactically matches
    # generated-index-v1 (-> would-be PX-0192) but the explicit override
    # must win, per implementation-notes.md ("the canonical fixture wins").
    result = resolver.resolve("ERP", "PART-00192")
    assert isinstance(result, Resolved)
    assert result.canonical_id == "PX-17"
    assert result.canonical_id != "PX-0192"


# --- ambiguous / unrecognized -> quarantine (F09) --------------------------


@pytest.mark.parametrize(
    "system,local_id",
    [
        ("ERP", "PART-XYZ"),  # not 5 digits
        ("ERP", "PART-1"),  # too short
        ("MES", "COMP-999999"),  # too many digits
        ("WMS", "SKU-1"),  # too short
        ("ERP", ""),  # empty
        ("ERP", "part-00007"),  # wrong case, no rule accepts it
    ],
)
def test_unrecognized_source_id_is_quarantined_not_guessed(resolver: IdentityResolver, system, local_id):
    result = resolver.resolve(system, local_id)
    assert isinstance(result, Quarantined), f"expected quarantine for {system}/{local_id!r}, got {result}"
    assert result.reason == "unrecognized_source_identifier_format"


def test_quarantine_never_returns_a_guessed_canonical_id(resolver: IdentityResolver):
    result = resolver.resolve("ERP", "PART-NOT-A-REAL-ID")
    assert isinstance(result, Quarantined)
    assert not hasattr(result, "canonical_id")


# --- metamorphic: rename source id, same canonical result ------------------


def test_source_id_rename_preserves_canonical_result(resolver: IdentityResolver):
    # contracts/identity/v1/mapping_rules.yaml's legacy-alias-v1 test
    # fixture: PART-LEGACY-00007 is a synthetic alias for the same
    # canonical part generated-index-v1 derives from PART-00007 (i=7).
    renamed = resolver.resolve("ERP", "PART-LEGACY-00007")
    original = resolver.resolve("ERP", "PART-00007")
    assert isinstance(renamed, Resolved) and isinstance(original, Resolved)
    assert renamed.canonical_id == original.canonical_id == "PX-0007"
    # The mapping RULE used legitimately differs (alias -> explicit
    # override, original -> pattern rule) — the metamorphic invariant is on
    # the canonical RESULT, not the rule that produced it.
    assert renamed.rule_id != original.rule_id


# --- every Resolved/Quarantined result carries required provenance --------


def test_resolved_result_carries_full_provenance(resolver: IdentityResolver):
    result = resolver.resolve("ERP", "PART-00007")
    assert isinstance(result, Resolved)
    assert result.rule_id and result.rule_version
    assert result.source_system == "ERP" and result.source_local_id == "PART-00007"
    assert result.authority
    assert 0.0 < result.confidence <= 1.0
    assert result.resolved_at is not None
