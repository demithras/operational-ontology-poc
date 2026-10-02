"""Registered Domain 2 requirements (docs/04 object types, links, lifecycle, hard rules; docs/05 properties).

Each requirement names the project-IR resources that carry it. ``check`` verifies every carrier exists in the IR
(by kind and id, links also by endpoints), that its kind is a kernel kind, and that it compiled through the Engine's
DISPATCH_TABLE. Mapping is declared HERE (registry), judged by code: a carrier that does not exist is a failure.
"""
from __future__ import annotations

TYPES = ["Hypothesis", "Rival", "Prediction", "Falsifier", "Experiment", "Metric", "Threshold", "Evidence", "Verdict",
         "Component", "ContractVersion", "Commit", "Test", "Decision", "Failure"]
LINKS = [("HAS_RIVAL", "Hypothesis", "Rival"), ("PREDICTS", "Hypothesis", "Prediction"),
         ("FALSIFIED_BY", "Hypothesis", "Falsifier"), ("TESTED_BY", "Hypothesis", "Experiment"),
         ("MEASURES", "Experiment", "Metric"), ("GOVERNED_BY", "Metric", "Threshold"),
         ("PRODUCES", "Experiment", "Evidence"), ("SUPPORTS_OR_REFUTES", "Evidence", "Hypothesis"),
         ("EVALUATES", "Verdict", "Hypothesis"), ("CAPTURED_AT", "Evidence", "Commit"),
         ("EXISTS_FOR", "Component", "Hypothesis"), ("VALIDATES", "Test", "Component"),
         ("DETECTED_BY", "Failure", "Test"), ("CHANGES", "Decision", "ContractVersion")]
STATES = {"DRAFT": "create_hypothesis", "PREREGISTERED": "preregister_hypothesis", "RUNNING": "start_run",
          "EVALUATED": "evaluate_hypothesis", "SUPERSEDED": "supersede_hypothesis"}
O, L, F, A, P, AU, C, OB = ("object_types", "link_types", "functions", "actions", "policies", "authority_rules",
                            "constraints", "observation_types")
HARD = {  # docs/04 hard rule -> carriers (kind, id)
    "preregistration_completeness": [(P, "preregistration_requires_complete_contract"), (C, "preregistration-complete-contract"),
                                     (A, "preregister_hypothesis")],
    "post_freeze_immutability": [(P, "threshold_edit_after_preregistration_denied"), (C, "threshold-immutable-after-preregistration"),
                                 (C, "falsifier-immutable-after-preregistration"), (C, "evaluator-immutable-after-preregistration"),
                                 (AU, "no-threshold-edit-after-preregistration"), (A, "new_experiment_version")],
    "running_requires_freeze_hash": [(P, "running_requires_freeze_hash"), (C, "running-requires-freeze-hash"), (A, "start_run"),
                                     (F, "compute_freeze_hash")],
    "evaluated_requires_evidence_or_reason": [(P, "evaluated_requires_evidence_or_reason"), (C, "evaluated-requires-evidence-or-reason"),
                                              (A, "evaluate_hypothesis"), (F, "evidence_count")],
    "verdict_machine_derived": [(P, "verdict_must_be_machine_derived"), (C, "verdict-machine-derived"), (C, "verdict-vocabulary"),
                                (C, "supported-needs-evidence"), (AU, "no-direct-verdict-write"), (F, "derive_verdict")],
    "evidence_binds_version_commit_environment": [(P, "evidence_must_bind_version_commit_environment"),
                                                  (C, "evidence-bound-to-version-commit-environment"), (A, "attach_evidence")],
    "orphan_flagged_not_deleted": [(P, "orphan_component_is_flagged_not_deleted"), (C, "orphan-component-flagged-not-deleted"),
                                   (A, "flag_orphan_component"), (F, "find_orphan_components")],
}
GIT = {  # docs/05 required property -> carriers
    "rebuild_reproduces_state_hash": [(C, "rebuild-reproduces-state-hash"), (F, "canonical_state_hash")],
    "durable_actions_are_git_changes": [(C, "durable-actions-are-git-changes"), (AU, "no-canonical-write-outside-git")],
    "no_silent_stale_write": [(P, "stale_write_rejected"), (C, "no-silent-stale-write")],
    "conflicts_surface_explicitly": [(P, "conflicting_change_denied_with_conflict"), (C, "conflicts-surface-explicitly")],
    "ephemeral_state_marked": [(P, "ephemeral_state_never_canonical"), (C, "ephemeral-state-marked")],
    "historical_binding_preserved": [(P, "historical_binding_preserved"), (C, "historical-binding-preserved"),
                                     (O, "ContractVersion")],
}
PROPS = [("Hypothesis", "phase"), ("Hypothesis", "freeze_hash"), ("Experiment", "version"), ("Experiment", "freeze_hash"),
         ("Evidence", "git_commit"), ("Evidence", "experiment_version"), ("Evidence", "environment"),
         ("Component", "orphan_flagged"), ("Verdict", "derivation_hash")]


def registry() -> list[dict]:
    """The registered requirement list: {id, source, carriers: [(kind, id[, extra])]}."""
    out = [{"id": f"type:{t}", "source": "docs/04 required object types", "carriers": [(O, t)]} for t in TYPES]
    out += [{"id": f"link:{n}", "source": "docs/04 required links", "carriers": [(L, n, (f, t))]} for n, f, t in LINKS]
    out += [{"id": f"state:{s}", "source": "docs/04 executable lifecycle",
             "carriers": [(A, act), (C, "lifecycle-order"), (P, "legal_lifecycle_transition_allowed"),
                          (F, "is_legal_transition"), (O, "Hypothesis")]} for s, act in STATES.items()]
    out += [{"id": "state:terminal_verdicts", "source": "docs/04 executable lifecycle",
             "carriers": [(C, "verdict-vocabulary"), (O, "Verdict")]}]
    out += [{"id": f"rule:{k}", "source": "docs/04 hard rules", "carriers": v} for k, v in HARD.items()]
    out += [{"id": f"git:{k}", "source": "docs/05 required properties", "carriers": v} for k, v in GIT.items()]
    out += [{"id": f"prop:{t}.{p}", "source": "docs/04 hard-rule properties", "carriers": [("property", t, p)]} for t, p in PROPS]
    return out
