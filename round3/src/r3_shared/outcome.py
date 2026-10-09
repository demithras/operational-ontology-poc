"""Outcome vocabulary and form ONLY (PROT-H28 R28-4, P1f-6). There is deliberately NO outcome function here: the function
is implemented separately by r3_oracle and by each variant (ruling Q4); conformance C28-2 compares them."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

STATES = ("PENDING", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED", "UNKNOWN")
CONFIDENCES = ("full", "low")
KEYS = ("request_id", "effect_index", "system", "state", "confidence", "evidence")
FINAL_STATES = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")
LOW_CONFIDENCE_OBSERVABILITY = ("none", "effects_only")
_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "external-outcome.schema.json").read_text())


class OutcomeFormError(ValueError):
    """An OUTCOME record violated the frozen form."""


def validate_outcome(o: dict) -> dict:
    """Exact six keys, exact vocabulary, evidence = strictly increasing positive ints (sorted, no duplicates), no bools."""
    if not isinstance(o, dict):
        raise OutcomeFormError("outcome: not an object")
    try:
        jsonschema.validate(o, _SCHEMA)
    except jsonschema.ValidationError as exc:
        raise OutcomeFormError(f"outcome: {exc.message}") from exc
    if isinstance(o["effect_index"], bool) or any(isinstance(x, bool) for x in o["evidence"]):
        raise OutcomeFormError("outcome: bool is not an int")
    if o["evidence"] != sorted(set(o["evidence"])):
        raise OutcomeFormError("outcome: evidence must be sorted without duplicates")
    return o


def validate_outcomes(body: dict) -> list[dict]:
    """The body of dispatch/reconcile/outcome results: {"outcomes": [OUTCOME...]} sorted by (request, effect_index)."""
    if not isinstance(body, dict) or "outcomes" not in body or not isinstance(body["outcomes"], list):
        raise OutcomeFormError("body must carry an `outcomes` list")
    outs = [validate_outcome(o) for o in body["outcomes"]]
    if [(o["request_id"], o["effect_index"]) for o in outs] != sorted((o["request_id"], o["effect_index"]) for o in outs):
        raise OutcomeFormError("outcomes must be sorted by (request_id, effect_index)")
    if len({(o["request_id"], o["effect_index"]) for o in outs}) != len(outs):
        raise OutcomeFormError("duplicate (request_id, effect_index)")
    return outs


def allowed_transition(prev: str, new: str) -> bool:
    """P1f-6: RECONCILED_* and DIVERGED move only to DIVERGED (or stay); PENDING/UNKNOWN -> any."""
    if prev not in STATES or new not in STATES:
        return False
    if prev in ("PENDING", "UNKNOWN"):
        return True
    return new == prev or new == "DIVERGED"
