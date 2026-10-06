"""Verdict enum, common precedence and the dual-track verdict record.

evaluate_common copies the logic of round2/src/hdd/verdict.py:evaluate_common (upstream pin 8f9ff26).
Missing evidence can never become SUPPORTED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
    """INVALID > REJECTED > INCONCLUSIVE (missing evidence / small sample) > SUPPORTED > INCONCLUSIVE.

    Strict: only the literal True counts as a hit/valid; None or any other value is treated as missing.
    """
    if x.protocol_valid is not True:
        return Verdict.INVALID
    if x.reject_hit is True:
        return Verdict.REJECTED
    if x.required_evidence_complete is not True or x.sample_sufficient is not True:
        return Verdict.INCONCLUSIVE
    if x.support_hit is True:
        return Verdict.SUPPORTED
    return Verdict.INCONCLUSIVE


def evaluate_from_mapping(m: dict[str, Any] | None) -> Verdict:
    """Build a CommonEvaluation from a possibly incomplete mapping. Missing keys: protocol_valid -> INVALID,
    everything else -> not satisfied (never SUPPORTED)."""
    m = m or {}
    return evaluate_common(CommonEvaluation(
        protocol_valid=m.get("protocol_valid"), required_evidence_complete=m.get("required_evidence_complete"),
        sample_sufficient=m.get("sample_sufficient"), reject_hit=m.get("reject_hit"),
        support_hit=m.get("support_hit")))


COMPARATIVE_FIELDS = ("forbidden_effects", "safe_progress_ratio", "mutation_kill_rate", "p95_latency_ms",
                      "security_specific_loc", "security_specific_components")


@dataclass
class DualVerdict:
    """protocol/DUAL_TRACK.json per_gate_verdicts: {paladin_verdict, conventional_verdict, comparative}.

    comparative is descriptive only; a gate where both pass is parity, not Paladin value (H30 owns value)."""
    paladin_verdict: Verdict | None
    conventional_verdict: Verdict | None
    comparative: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        def v(x):
            return Verdict.INCONCLUSIVE.value if x is None else Verdict(x).value
        comp = {k: self.comparative.get(k) for k in COMPARATIVE_FIELDS}
        comp.update({k: x for k, x in self.comparative.items() if k not in comp})
        return {"paladin_verdict": v(self.paladin_verdict), "conventional_verdict": v(self.conventional_verdict),
                "comparative": comp}
