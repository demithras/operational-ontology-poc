from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class CommonEvaluation:
    protocol_valid: bool
    required_evidence_complete: bool
    sample_sufficient: bool
    reject_hit: bool
    support_hit: bool


def evaluate_common(x: CommonEvaluation) -> Verdict:
    """Pack-wide verdict precedence.

    Specific hypotheses must provide their own deterministic support/reject
    predicates, then feed the booleans here. Missing evidence can never become
    support by default.
    """
    if not x.protocol_valid:
        return Verdict.INVALID
    if x.reject_hit:
        return Verdict.REJECTED
    if not x.required_evidence_complete or not x.sample_sufficient:
        return Verdict.INCONCLUSIVE
    if x.support_hit:
        return Verdict.SUPPORTED
    return Verdict.INCONCLUSIVE


def h22_gate(real_domains: int, blind_tasks: int, *, min_domains: int = 3, min_tasks: int = 30) -> bool:
    return real_domains >= min_domains and blind_tasks >= min_tasks
