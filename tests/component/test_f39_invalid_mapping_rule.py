"""F39 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"invalid mapping rule deployment -> identity -> compatibility fixture
catches or ambiguity exposed").

services/identity_resolver/resolver.py::IdentityResolver already validates
contracts/identity/v1/mapping_rules.yaml AT LOAD TIME (docs/experiment/spec/04_architecture.md:
"Ambiguous identity is a first-class failure, not silently guessed") — this
test is the FIRST one to actually exercise that validation against a
deliberately invalid deployment, proving the ambiguity is exposed loudly
(a real exception at load time) rather than silently resolved to whichever
rule happened to be read last.
"""

from __future__ import annotations

import pytest
import yaml

from services.identity_resolver.resolver import ConflictingMappingRuleError, IdentityResolver


def _write_rules(tmp_path, rules_doc: dict):
    path = tmp_path / "mapping_rules.yaml"
    path.write_text(yaml.safe_dump(rules_doc))
    return path


def test_f39_conflicting_explicit_overrides_for_same_source_id_is_caught(tmp_path):
    """The realistic F39 shape: two rules in the SAME deployed file both
    claim canonical ownership of the identical (system, local_id) pair —
    an operator error a compatibility check must catch before it ever
    reaches live resolution (where it would silently resolve to whichever
    rule the loader happened to process first)."""
    bad_rules = {
        "version": "9",
        "rules": [
            {
                "rule_id": "override-a", "version": "9", "kind": "explicit_override",
                "authority": "fixture-override", "confidence": 1.0,
                "entries": [{"canonical_id": "PX-9001", "source_ids": {"ERP": "PART-CONFLICT"}}],
            },
            {
                "rule_id": "override-b", "version": "9", "kind": "explicit_override",
                "authority": "fixture-override", "confidence": 1.0,
                # SAME (system, local_id) as override-a, DIFFERENT canonical_id.
                "entries": [{"canonical_id": "PX-9002", "source_ids": {"ERP": "PART-CONFLICT"}}],
            },
        ],
    }
    path = _write_rules(tmp_path, bad_rules)
    with pytest.raises(ConflictingMappingRuleError, match="PART-CONFLICT"):
        IdentityResolver(rules_path=path)


def test_f39_unknown_rule_kind_is_caught(tmp_path):
    """A deployed rule using a kind the resolver has never heard of (e.g.
    a typo, or a schema evolution the resolver code hasn't caught up
    with) fails loudly at load time rather than being silently skipped."""
    bad_rules = {
        "version": "9",
        "rules": [{"rule_id": "typo-rule", "version": "9", "kind": "explicit_overide", "entries": []}],
    }
    path = _write_rules(tmp_path, bad_rules)
    with pytest.raises(ValueError, match="unknown rule kind"):
        IdentityResolver(rules_path=path)


def test_f39_pattern_rule_missing_canonical_template_is_caught(tmp_path):
    """A pattern rule published without the required canonical_template key
    — a real, plausible way to ship a broken mapping-rule deployment (e.g.
    a copy-paste that dropped one field) — fails loudly rather than being
    silently accepted and only breaking on the FIRST live resolve() call
    against production traffic."""
    bad_rules = {
        "version": "9",
        "rules": [{
            "rule_id": "broken-pattern", "version": "9", "kind": "pattern",
            "authority": "system-generated", "confidence": 0.9,
            "patterns": {"ERP": {"regex": r"^PART-(\d{5})$", "offset": 0}},
            # canonical_template deliberately omitted.
        }],
    }
    path = _write_rules(tmp_path, bad_rules)
    with pytest.raises(KeyError, match="canonical_template"):
        IdentityResolver(rules_path=path)


def test_f39_valid_deployment_still_loads_and_resolves_correctly(tmp_path):
    """Known-negative counterpart (this repo's own established pattern,
    "before-recommending... verify against a known-positive"): a
    STRUCTURALLY VALID mapping-rule file must still load and resolve —
    proving the three tests above are catching genuine invalidity, not
    just rejecting every file."""
    good_rules = {
        "version": "9",
        "rules": [{
            "rule_id": "good-pattern", "version": "9", "kind": "pattern",
            "authority": "system-generated", "confidence": 0.9,
            "patterns": {"ERP": {"regex": r"^PART-(\d{5})$", "offset": 0}},
            "canonical_template": "PX-{i:04d}",
        }],
    }
    path = _write_rules(tmp_path, good_rules)
    resolver = IdentityResolver(rules_path=path)
    result = resolver.resolve("ERP", "PART-00042")
    assert result.canonical_id == "PX-0042", result
