"""Maps source-local part identifiers (ERP PART-xxxxx / MES COMP-xxx / WMS
SKU-xxxxx) to canonical part:PX-nn IRIs, per the versioned rule set at
contracts/identity/v1/mapping_rules.yaml.

docs/experiment/spec/04_architecture.md "Identity resolver": every mapping
records rule id/version, source ids, authority/confidence, creation time.
An ambiguous/unrecognized source id is a typed Quarantined result — never a
guess (F09, docs/experiment/spec/09_failure_and_adversarial_matrix.md).

No eval/exec: pattern rules are plain regex + integer offset arithmetic,
read declaratively from YAML (see mapping_rules.yaml's own comment on this).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import yaml

DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "identity" / "v1" / "mapping_rules.yaml"
)


@dataclass(frozen=True)
class Resolved:
    canonical_id: str
    rule_id: str
    rule_version: str
    authority: str
    confidence: float
    source_system: str
    source_local_id: str
    resolved_at: datetime


@dataclass(frozen=True)
class Quarantined:
    reason: str
    source_system: str
    source_local_id: str
    resolved_at: datetime


ResolutionResult = Union[Resolved, Quarantined]


class ConflictingMappingRuleError(ValueError):
    """Raised at load time when mapping_rules.yaml itself deploys two
    explicit overrides that disagree about one (system, local_id)'s
    canonical id — F39 ("invalid mapping rule deployment")."""


class IdentityResolver:
    def __init__(self, rules_path: Path = DEFAULT_RULES_PATH):
        self.rules_path = rules_path
        raw = yaml.safe_load(rules_path.read_text())
        self.rules_version = str(raw["version"])

        # (system, local_id) -> (canonical_id, rule_meta). Populated in file
        # order, i.e. priority order among explicit-override rules; a
        # within-file disagreement about the SAME key is a deployment bug,
        # not runtime ambiguity, so it fails fast at load time.
        self._explicit: dict[tuple[str, str], tuple[str, dict]] = {}
        self._pattern_rules: list[dict] = []

        for rule in raw["rules"]:
            kind = rule["kind"]
            if kind == "explicit_override":
                for entry in rule["entries"]:
                    canonical = entry["canonical_id"]
                    for system, local_id in entry["source_ids"].items():
                        key = (system, local_id)
                        if key in self._explicit and self._explicit[key][0] != canonical:
                            raise ConflictingMappingRuleError(
                                f"{rules_path}: (system={system!r}, local_id={local_id!r}) is claimed by "
                                f"both canonical_id={self._explicit[key][0]!r} and canonical_id={canonical!r}"
                            )
                        self._explicit[key] = (canonical, rule)
            elif kind == "pattern":
                compiled: dict[str, tuple[re.Pattern[str], int]] = {}
                for system, spec in rule["patterns"].items():
                    compiled[system] = (re.compile(spec["regex"]), int(spec["offset"]))
                self._pattern_rules.append(
                    {"meta": rule, "compiled": compiled, "template": rule["canonical_template"]}
                )
            else:
                raise ValueError(f"{rules_path}: unknown rule kind {kind!r}")

    def resolve(self, system: str, local_id: str) -> ResolutionResult:
        now = datetime.now(timezone.utc)
        key = (system, local_id)

        explicit = self._explicit.get(key)
        if explicit is not None:
            canonical, meta = explicit
            return Resolved(
                canonical_id=canonical,
                rule_id=meta["rule_id"],
                rule_version=str(meta["version"]),
                authority=meta["authority"],
                confidence=float(meta["confidence"]),
                source_system=system,
                source_local_id=local_id,
                resolved_at=now,
            )

        for rule in self._pattern_rules:
            compiled = rule["compiled"].get(system)
            if compiled is None:
                continue
            regex, offset = compiled
            match = regex.match(local_id)
            if match is None:
                continue
            index = int(match.group(1)) - offset
            canonical = rule["template"].format(i=index)
            meta = rule["meta"]
            return Resolved(
                canonical_id=canonical,
                rule_id=meta["rule_id"],
                rule_version=str(meta["version"]),
                authority=meta["authority"],
                confidence=float(meta["confidence"]),
                source_system=system,
                source_local_id=local_id,
                resolved_at=now,
            )

        return Quarantined(
            reason="unrecognized_source_identifier_format",
            source_system=system,
            source_local_id=local_id,
            resolved_at=now,
        )
