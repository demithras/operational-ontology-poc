"""Shared contract-version constants.

docs/experiment/spec/01_hypotheses.md H1/H6 and
docs/experiment/spec/07_versioning_and_replay.md both require every
governed artifact (decisions, projection rows) to carry the ontology
contract version it was computed/evaluated under. This repo currently has
exactly one ontology contract on disk (contracts/ontology/v1/), matching
contracts/shapes/v1/ and contracts/projections/v1/ — all three "v1"
directory names ARE the version identifier for now (07_versioning_and_replay.md's
V2/V3 migration experiment, Phase 7, is what introduces a second value here).
"""

from __future__ import annotations

ONTOLOGY_CONTRACT_VERSION = "v1"
