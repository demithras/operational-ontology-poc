"""Project Ontology Function implementations, keyed by Function.implementation_ref: impl(view, args) -> value."""
from __future__ import annotations

from . import facts, freeze
from .constraints import state_hash
from .lifecycle import legal_transition


def make(deriver, reader) -> dict:
    return {
        "fn:evidence_count:v1": lambda view, a: facts.evidence_count(view, a["hypothesis"]),
        "scripts/freeze_protocol.py": lambda view, a: freeze.compute_freeze_hash(view, a["experiment"], reader),
        "src/hdd/verdict.py:evaluate_common": lambda view, a: deriver.derive(view, a["hypothesis"])["verdict"],
        "fn:find_orphan_components:v1": lambda view, a: facts.active_components_missing(view),
        "fn:canonical_state_hash:v1": lambda view, a: state_hash(view),
        "src/hdd/project_lifecycle_reference.py":
            lambda view, a: legal_transition(facts.props(view, "Hypothesis", a["hypothesis"]).get("phase"), a["target_phase"]),
    }
