"""Assemble the Project Ontology IR + provenance (docs/04_project_ontology_domain.md + docs/05_git_authority.md)."""
from __future__ import annotations

from .common import Builder
from .prj_gov import add_actions, add_authority, add_constraints, add_policies
from .prj_model import add_functions, add_interfaces, add_links, add_objects, add_observations

DECISIONS = [
    "Scope: docs/04_project_ontology_domain.md and docs/05_git_authority.md define the domain; the 15 required object types (Hypothesis, Rival, Prediction, Falsifier, Experiment, Metric, Threshold, Evidence, Verdict, Component, ContractVersion, Commit, Test, Decision, Failure) are all present and no further ordinary type was added. Property lists are NOT in the docs; the minimum needed by the hard rules was chosen (e.g. Hypothesis.phase/freeze_hash, Evidence.payload_hash/git_commit/experiment_version/environment, Verdict.value/reason/derivation_hash/git_commit). Each is a choice traced to the rule that needs it.",
    "Link vocabulary: the 14 links of docs/04_project_ontology_domain.md 'Required links' are used verbatim as ids (HAS_RIVAL ... CHANGES). SUPERSEDED_BY is added because the lifecycle says a hypothesis may be 'SUPERSEDED by a new hypothesis/version' and the docs list no link for it. Cardinalities are not stated anywhere in the docs: every multiplicity is a choice (convention from the frozen example: from_cardinality = links per FROM instance, to_cardinality = links per TO instance). A rival/prediction/falsifier/experiment/evidence belongs to exactly one hypothesis/experiment ({1,1} on the to-end); preregistration needs at least one rival/prediction/falsifier, but that is a lifecycle rule (policy), so the from-end minimum is 0 (DRAFT hypotheses may have none).",
    "The 'hard rules' of docs/04_project_ontology_domain.md are carried as Policies (decision deny/classify/allow, one per rule, for governed Actions) AND as Constraints (hard/soft, for the invariants that must hold of the state). Both are listed so neither surface can be accused of hiding a rule; they are not duplicates in meaning (policy gates an Action, constraint states an invariant). The only soft constraint is the orphan flag (docs/04_project_ontology_domain.md: flagged, not deleted).",
    "Authority: docs/04_project_ontology_domain.md and docs/05_git_authority.md name no roles or permissions. The frozen example project-domain-minimal.json uses `role:researcher` for preregistration; that role was extended to every lifecycle Action (one allow rule each). The three deny rules come from clauses: no direct write of Verdict.value (hard rule 5), no threshold edit after preregistration (hard rule 2), no canonical write outside Git (docs/05_git_authority.md, AGENTS.md section 12). Who may do what beyond that is a gap in the docs; delegation_allowed is false everywhere because no clause mentions delegation.",
    "Actions: the lifecycle verbs are create_hypothesis, edit_threshold (DRAFT only), preregister_hypothesis, new_experiment_version, start_run, attach_evidence, evaluate_hypothesis, supersede_hypothesis, record_decision, flag_orphan_component. Every effect is operation `git_change` (docs/05_git_authority.md property 2: every durable action is a versioned Git change). evaluate_hypothesis takes no verdict input: the verdict is computed by the Function derive_verdict (hard rule 5). compensation_action is null everywhere: a Git revert is not a modelled Action in the docs.",
    "Functions: evidence_count (frozen example), compute_freeze_hash, derive_verdict, find_orphan_components, canonical_state_hash, is_legal_transition. Where code exists the implementation_ref points at it (scripts/freeze_protocol.py, src/hdd/verdict.py, src/hdd/project_lifecycle_reference.py); the others use the `fn:<name>:v1` convention of the frozen examples and are marked implementation pending in their note. These are IR contracts, not implementations.",
    "Observation types: TestRunObserved (source pytest) and GitCommitObserved (source git) from docs/04_project_ontology_domain.md (Test, Commit) and docs/05_git_authority.md (Git as the observable canonical source). The docs give no source_binding strings; `pytest` and `git` are the obvious tool names.",
    "Preconditions and outcome predicates are free-text atoms written from the clause they enforce; they are not executable expressions.",
    "Interfaces: VersionedResearchObject (from the frozen example; implemented by six object types) and GitBound (docs/05_git_authority.md property 6 and docs/04_project_ontology_domain.md hard rule 6; implemented by Evidence, Verdict, ContractVersion) are the two genuine shared shapes in the docs. Commit identifies itself by `sha`, not `id`, so it does not implement VersionedResearchObject.",
    "Package metadata: the package id `project-ontology`, domain id `operational-ontology-poc` and version `v1` follow ontology/examples/project-domain-minimal.json (the frozen example for this domain).",
]


def build():
    b = Builder("project-ontology", "operational-ontology-poc", "v1", {"derived_from": "docs/04_project_ontology_domain.md, docs/05_git_authority.md, AGENTS.md, src/hdd"})
    add_interfaces(b)
    add_objects(b)
    add_links(b)
    add_functions(b)
    add_policies(b)
    add_authority(b)
    add_actions(b)
    add_observations(b)
    add_constraints(b)
    for d in DECISIONS:
        b.decide(d)
    return b
