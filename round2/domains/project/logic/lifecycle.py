"""is_legal_transition via the independent reference model (src/hdd/project_lifecycle_reference.py)."""
from __future__ import annotations

from hdd.project_lifecycle_reference import (HypothesisState, InvalidTransition, Phase, ScientificVerdict, evaluate,
                                             preregister, start, supersede)

_GUARDS = {"PREREGISTERED": lambda s: preregister(s, "x"), "RUNNING": start,
           "EVALUATED": lambda s: evaluate(s, ScientificVerdict.SUPPORTED), "SUPERSEDED": supersede}


def legal_transition(current: str, target: str) -> bool:
    """True iff the reference model's guard for ``target`` accepts a hypothesis in phase ``current`` whose other
    conditions (contract complete, freeze hash, evidence) are satisfied: the phase order alone is decided here."""
    guard = _GUARDS.get(target)
    if guard is None or current not in Phase.__members__:
        return False
    try:
        guard(HypothesisState(phase=Phase(current), freeze_hash="x", evidence_count=1))
    except InvalidTransition:
        return False
    return True
