"""MUTANT policy_gate_in_adapter (PROT-H28 s9, Q10). Loaded by name ONLY when the mutant is active (never part of a clean
build's import closure; see ConventionalVariant.adapter_modules). The approval rules `expedite-large-fee-needs-approval` and
`publish-public-needs-approval` are re-implemented here, adapter-side, and block the submit while the decision plane commits OK.
"""
from __future__ import annotations


def holds(system: str, op: str, payload: dict) -> bool:
    if (system, op) == ("ERP", "expedite"):
        return payload.get("expedite_fee", 0) > 500
    if (system, op) == ("REGISTRY", "publish"):
        return payload.get("visibility") == "public"
    return False
