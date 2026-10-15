"""Independent pure reference model for Project Ontology lifecycle.

This is deliberately tiny. The real EOO must be differential-tested against it;
it must not import EOO runtime code.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Phase(str, Enum):
    DRAFT = "DRAFT"
    PREREGISTERED = "PREREGISTERED"
    RUNNING = "RUNNING"
    EVALUATED = "EVALUATED"
    SUPERSEDED = "SUPERSEDED"


class ScientificVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class HypothesisState:
    phase: Phase = Phase.DRAFT
    has_claim: bool = True
    has_rival: bool = True
    has_predictions: bool = True
    has_falsifier: bool = True
    has_evidence_schema: bool = True
    has_evaluator: bool = True
    threshold_revision: int = 0
    freeze_hash: str | None = None
    evidence_count: int = 0
    evidence_commit_pinned: bool = True
    verdict: ScientificVerdict | None = None


class InvalidTransition(ValueError):
    pass


def preregister(s: HypothesisState, freeze_hash: str) -> HypothesisState:
    if s.phase != Phase.DRAFT:
        raise InvalidTransition("only DRAFT may preregister")
    required = [s.has_claim, s.has_rival, s.has_predictions, s.has_falsifier, s.has_evidence_schema, s.has_evaluator]
    if not all(required) or not freeze_hash:
        raise InvalidTransition("incomplete preregistration")
    return replace(s, phase=Phase.PREREGISTERED, freeze_hash=freeze_hash)


def edit_threshold(s: HypothesisState) -> HypothesisState:
    if s.phase != Phase.DRAFT:
        raise InvalidTransition("thresholds immutable after preregistration; create new experiment version")
    return replace(s, threshold_revision=s.threshold_revision + 1)


def start(s: HypothesisState) -> HypothesisState:
    if s.phase != Phase.PREREGISTERED or not s.freeze_hash:
        raise InvalidTransition("RUNNING requires preregistered freeze")
    return replace(s, phase=Phase.RUNNING)


def attach_evidence(s: HypothesisState, *, commit_pinned: bool) -> HypothesisState:
    if s.phase != Phase.RUNNING:
        raise InvalidTransition("evidence attaches only while RUNNING")
    if not commit_pinned:
        raise InvalidTransition("authoritative evidence must pin commit/version")
    return replace(s, evidence_count=s.evidence_count + 1, evidence_commit_pinned=True)


def evaluate(s: HypothesisState, verdict: ScientificVerdict) -> HypothesisState:
    if s.phase != Phase.RUNNING:
        raise InvalidTransition("only RUNNING can evaluate")
    if s.evidence_count == 0 and verdict not in {ScientificVerdict.INCONCLUSIVE, ScientificVerdict.INVALID}:
        raise InvalidTransition("support/reject require evidence")
    return replace(s, phase=Phase.EVALUATED, verdict=verdict)


def supersede(s: HypothesisState) -> HypothesisState:
    if s.phase != Phase.EVALUATED:
        raise InvalidTransition("only evaluated hypothesis can be superseded")
    return replace(s, phase=Phase.SUPERSEDED)
