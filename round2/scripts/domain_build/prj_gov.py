"""Project Ontology: policies, authority rules, governed Actions, constraints (docs/04_project_ontology_domain.md, docs/05_git_authority.md, AGENTS.md)."""
from __future__ import annotations

from .common import J, S, param, ref
from .prj_model import D4, D5

REF = "src/hdd/project_lifecycle_reference.py"
POLICIES = [  # (id, decision, expression, source, note)
    ("preregistration_requires_complete_contract", "deny", "docs/04#preregistration-completeness", D4 + " (hard rule 1: preregistration requires claim, strong rival, predictions, falsifiers, evidence schema and evaluator)", f"{REF}: preregister raises InvalidTransition on an incomplete contract"),
    ("threshold_edit_after_preregistration_denied", "deny", "docs/04#threshold-immutable", D4 + " (hard rule 2: after PREREGISTERED a threshold/falsifier/evaluator change creates a new experiment version)", f"{REF}: edit_threshold only in DRAFT"),
    ("running_requires_freeze_hash", "deny", "docs/04#running-needs-freeze-hash", D4 + " (hard rule 3: RUNNING requires a freeze hash)", f"{REF}: start requires PREREGISTERED and a freeze hash"),
    ("evaluated_requires_evidence_or_reason", "deny", "docs/04#evaluated-needs-evidence", D4 + " (hard rule 4: EVALUATED requires required evidence or an explicit INCONCLUSIVE/INVALID reason)", f"{REF}: evaluate"),
    ("verdict_must_be_machine_derived", "deny", "docs/04#verdict-machine-derived", D4 + " (hard rule 5: a SUPPORTED verdict is machine-derived, not arbitrary user input)", "denies any Verdict whose value is not the output of derive_verdict"),
    ("evidence_must_bind_version_commit_environment", "deny", "docs/04#evidence-binding", D4 + " (hard rule 6: every authoritative evidence artifact binds to experiment version + commit + environment)", f"{REF}: attach_evidence requires a commit-pinned artifact"),
    ("orphan_component_is_flagged_not_deleted", "classify", "docs/04#orphan-classification", D4 + " (hard rule 7: a component with no link to an active hypothesis is flagged as an orphan, not automatically deleted)", "classify = label, never reject"),
    ("stale_write_rejected", "deny", "docs/05#stale-write", D5 + " (property 3: the ontology cannot silently accept a stale write over a newer Git version)", ""),
    ("conflicting_change_denied_with_conflict", "deny", "docs/05#explicit-conflict", D5 + " (property 4: conflicting changes must surface an explicit conflict)", "compatible concurrent changes may merge (no policy); conflicting ones are denied and reported"),
    ("ephemeral_state_never_canonical", "deny", "docs/05#ephemeral-state", D5 + " (property 5: ephemeral runtime state is clearly marked and never confused with canonical project state)", ""),
    ("historical_binding_preserved", "deny", "docs/05#historical-binding", D5 + " (property 6: historical verdicts/evidence remain bound to the commit/version they were created under)", ""),
    ("legal_lifecycle_transition_allowed", "allow", "docs/04#lifecycle-order", D4 + " (Required executable lifecycle: DRAFT -> PREREGISTERED -> RUNNING -> EVALUATED -> SUPERSEDED)", f"{REF}: the guards of preregister/start/evaluate/supersede"),
]
ACTIONS = [  # (id, inputs, extra authority, policies, preconditions, effects, outcome, source)
    ("create_hypothesis", [param("claim", S)], [], ["stale_write_rejected", "ephemeral_state_never_canonical"], ["claim is non-empty"],
     [("Hypothesis", ["id", "claim", "phase"])], "Git contains the hypothesis contract at the expected commit with phase == DRAFT", D4 + " (lifecycle start: DRAFT)"),
    ("edit_threshold", [param("threshold", ref("Threshold")), param("value", J)], ["no-threshold-edit-after-preregistration"], ["threshold_edit_after_preregistration_denied", "stale_write_rejected"],
     ["phase == DRAFT"], [("Threshold", ["value"])], "Git contains the new threshold value while the hypothesis phase is still DRAFT", D4 + " (hard rule 2); " + REF + " (edit_threshold)"),
    ("preregister_hypothesis", [param("hypothesis", ref("Hypothesis")), param("freeze_hash", S)], [], ["preregistration_requires_complete_contract", "legal_lifecycle_transition_allowed", "stale_write_rejected"],
     ["phase == DRAFT", "freeze_hash exists"], [("Hypothesis", ["phase", "freeze_hash"])], "Git contains preregistered contract at expected commit", D4 + " (hard rule 1); ontology/examples/project-domain-minimal.json (preregister_hypothesis)"),
    ("new_experiment_version", [param("experiment", ref("Experiment")), param("contract_version", ref("ContractVersion"))], [], ["threshold_edit_after_preregistration_denied", "historical_binding_preserved", "stale_write_rejected"],
     ["phase != DRAFT"], [("Experiment", ["id", "version", "evidence_schema_ref", "evaluator_ref"]), ("ContractVersion", ["id", "sha256", "git_commit", "frozen_at"])],
     "Git contains a new Experiment row with a new version and the matching ContractVersion; the old experiment version is unchanged", D4 + " (hard rule 2: creates a new experiment version); AGENTS.md section 6 (freeze discipline)"),
    ("start_run", [param("hypothesis", ref("Hypothesis"))], [], ["running_requires_freeze_hash", "legal_lifecycle_transition_allowed", "stale_write_rejected"],
     ["phase == PREREGISTERED", "freeze_hash exists"], [("Hypothesis", ["phase"])], "Git contains the hypothesis with phase == RUNNING at the expected commit", D4 + " (hard rule 3); " + REF + " (start)"),
    ("attach_evidence", [param("hypothesis", ref("Hypothesis")), param("evidence", ref("Evidence"))], [], ["evidence_must_bind_version_commit_environment", "historical_binding_preserved", "stale_write_rejected"],
     ["phase == RUNNING", "evidence is pinned to experiment version, commit and environment"], [("Evidence", ["id", "payload_hash", "git_commit", "experiment_version", "environment"]), ("PRODUCES", None)],
     "Git contains the evidence artifact bound to the experiment version, commit and environment", D4 + " (hard rule 6); " + REF + " (attach_evidence)"),
    ("evaluate_hypothesis", [param("hypothesis", ref("Hypothesis"))], ["no-direct-verdict-write"], ["evaluated_requires_evidence_or_reason", "verdict_must_be_machine_derived", "legal_lifecycle_transition_allowed", "stale_write_rejected"],
     ["phase == RUNNING", "evidence_count(hypothesis) >= 1 or an explicit INCONCLUSIVE/INVALID reason is given"],
     [("Verdict", ["id", "value", "reason", "derivation_hash", "git_commit"]), ("Hypothesis", ["phase"]), ("EVALUATES", None)],
     "Git contains a Verdict whose value equals derive_verdict(hypothesis) and the hypothesis with phase == EVALUATED", D4 + " (hard rules 4 and 5); " + REF + " (evaluate); src/hdd/verdict.py"),
    ("supersede_hypothesis", [param("hypothesis", ref("Hypothesis")), param("successor", ref("Hypothesis"))], [], ["legal_lifecycle_transition_allowed", "historical_binding_preserved", "stale_write_rejected"],
     ["phase == EVALUATED"], [("Hypothesis", ["phase"]), ("SUPERSEDED_BY", None)], "Git contains the hypothesis with phase == SUPERSEDED and a SUPERSEDED_BY link to the successor", D4 + " (lifecycle: optionally SUPERSEDED); " + REF + " (supersede)"),
    ("record_decision", [param("decision", ref("Decision")), param("contract_version", ref("ContractVersion"))], [], ["stale_write_rejected", "historical_binding_preserved"],
     ["rationale is non-empty"], [("Decision", ["id", "rationale", "decided_at"]), ("CHANGES", None)], "Git contains the decision and its CHANGES link to the contract version", D4 + " (Decision CHANGES ContractVersion)"),
    ("flag_orphan_component", [param("component", ref("Component"))], [], ["orphan_component_is_flagged_not_deleted", "stale_write_rejected"],
     ["component is returned by find_orphan_components"], [("Component", ["orphan_flagged"])], "Git contains the component with orphan_flagged == true; the component is not deleted", D4 + " (hard rule 7)"),
]


def add_policies(b):
    for pid, dec, expr, src, note in POLICIES:
        b.policy(pid, dec, expr, "v1", src=src, note=note)


def add_authority(b):
    A = b.authority
    for act, *_ in ACTIONS:
        A(f"researcher-{act.replace('_', '-')}", "role:researcher", f"action:{act}", "Hypothesis:*" if "hypothesis" in act else "ProjectOntology:*", "allow", False,
          src="ontology/examples/project-domain-minimal.json (researcher-preregister pattern); " + D4,
          note="docs/04_project_ontology_domain.md and docs/05_git_authority.md name no roles; `researcher` is the role the frozen example uses, extended to every lifecycle action (see decisions)")
    A("no-direct-verdict-write", "*", "write:Verdict.value", "Verdict:*", "deny", False, src=D4 + " (hard rule 5: verdict is machine-derived, not user input)")
    A("no-threshold-edit-after-preregistration", "*", "update:Threshold", "Threshold:preregistered", "deny", False, src=D4 + " (hard rule 2)")
    A("no-canonical-write-outside-git", "*", "write:canonical-state", "ProjectOntology:*", "deny", False,
      src=D5 + " (Git = canonical authority; the ontology may not become a second source of truth); AGENTS.md section 12", note="every durable change must be a Git change")


def add_actions(b):
    for act, inputs, extra, pols, pre, effs, outcome, src in ACTIONS:
        effects = []
        for tgt, fields in effs:
            e = {"target": tgt, "operation": "git_change"}
            if fields is not None:
                e["fields"] = fields
            effects.append(e)
        auth = [f"researcher-{act.replace('_', '-')}", "no-canonical-write-outside-git"] + extra
        b.action(act, inputs, auth, pols, pre, effects, "required", outcome, None, "v1", src=src,
                 note="effect = a versioned Git change (docs/05_git_authority.md property 2); compensation null: a Git revert is not a modelled Action")


def add_constraints(b):
    C = b.constraint
    d4, d5 = D4, D5
    rows = [
        ("supported-needs-evidence", "Hypothesis", "constraint:supported-needs-evidence:v1", "hard", d4 + " (hard rule 4); ontology/examples/project-domain-minimal.json (same id)"),
        ("preregistration-complete-contract", "Hypothesis", "constraint:preregistration-complete-contract:v1", "hard", d4 + " (hard rule 1)"),
        ("threshold-immutable-after-preregistration", "Threshold", "constraint:threshold-immutable-after-preregistration:v1", "hard", d4 + " (hard rule 2)"),
        ("falsifier-immutable-after-preregistration", "Falsifier", "constraint:falsifier-immutable-after-preregistration:v1", "hard", d4 + " (hard rule 2)"),
        ("evaluator-immutable-after-preregistration", "Experiment", "constraint:evaluator-immutable-after-preregistration:v1", "hard", d4 + " (hard rule 2)"),
        ("running-requires-freeze-hash", "Hypothesis", "constraint:running-requires-freeze-hash:v1", "hard", d4 + " (hard rule 3)"),
        ("evaluated-requires-evidence-or-reason", "Hypothesis", "constraint:evaluated-requires-evidence-or-reason:v1", "hard", d4 + " (hard rule 4)"),
        ("verdict-machine-derived", "Verdict", "constraint:verdict-machine-derived:v1", "hard", d4 + " (hard rule 5)"),
        ("verdict-vocabulary", "Verdict", "enum:SUPPORTED|REJECTED|INCONCLUSIVE|INVALID on value", "hard", "AGENTS.md section 5 (verdict semantics); src/hdd/verdict.py"),
        ("evidence-bound-to-version-commit-environment", "Evidence", "constraint:evidence-bound-to-version-commit-environment:v1", "hard", d4 + " (hard rule 6)"),
        ("orphan-component-flagged-not-deleted", "Component", "constraint:orphan-component-flagged-not-deleted:v1", "soft", d4 + " (hard rule 7)"),
        ("lifecycle-order", "Hypothesis", "constraint:lifecycle-order:v1", "hard", d4 + " (Required executable lifecycle); " + REF),
        ("rebuild-reproduces-state-hash", "ProjectOntology", "constraint:rebuild-reproduces-state-hash:v1", "hard", d5 + " (property 1)"),
        ("durable-actions-are-git-changes", "ProjectOntology", "constraint:durable-actions-are-git-changes:v1", "hard", d5 + " (property 2)"),
        ("no-silent-stale-write", "ProjectOntology", "constraint:no-silent-stale-write:v1", "hard", d5 + " (property 3)"),
        ("conflicts-surface-explicitly", "ProjectOntology", "constraint:conflicts-surface-explicitly:v1", "hard", d5 + " (property 4)"),
        ("ephemeral-state-marked", "ProjectOntology", "constraint:ephemeral-state-marked:v1", "hard", d5 + " (property 5)"),
        ("historical-binding-preserved", "ProjectOntology", "constraint:historical-binding-preserved:v1", "hard", d5 + " (property 6)"),
    ]
    for cid, scope, expr, sev, src in rows:
        C(cid, scope, expr, sev, src=src, note="soft: flagged, never an error" if sev == "soft" else "")
