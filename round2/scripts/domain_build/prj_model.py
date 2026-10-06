"""Project Ontology: object types, interfaces, links, observation types, functions (docs/04_project_ontology_domain.md, docs/05_git_authority.md)."""
from __future__ import annotations

from .common import BO, DT, I, J, MANY, ONE, ONE_MANY, OPT1, S, enum, lst, p, param, ref

D4 = "docs/04_project_ontology_domain.md"
D5 = "docs/05_git_authority.md"
OBJ = f"{D4} (Required object types)"
PHASES = enum("DRAFT", "PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED")
VERDICTS = enum("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID")


def _id(extra=()):
    return [p("id", S, True, True)] + list(extra)


def add_interfaces(b):
    b.iface("VersionedResearchObject", [p("id", S, True, True)], caps=["read", "audit"],
            src="ontology/examples/project-domain-minimal.json (frozen example interface); " + D5 + " (every research object is Git-versioned)",
            note="implemented by every object type with an `id`: Hypothesis, Experiment, Evidence, Verdict, ContractVersion, Decision")
    b.iface("GitBound", [p("git_commit", S, True, True)], caps=["audit"],
            src=D5 + " (property 6: historical verdicts/evidence remain bound to the commit/version they were created under); " + D4 + " (every authoritative evidence artifact binds to experiment version + commit + environment)",
            note="implemented by Evidence, Verdict and ContractVersion")


def add_objects(b):
    O = b.obj
    VRO, GB = "VersionedResearchObject", "GitBound"
    O("Hypothesis", "id", _id([p("claim", S, True), p("phase", S, True, False, [PHASES]), p("freeze_hash")]), [VRO], src=OBJ + "; " + D4 + " (Required executable lifecycle)",
      note="phase = DRAFT -> PREREGISTERED -> RUNNING -> EVALUATED -> optionally SUPERSEDED; freeze_hash is set at preregistration and required for RUNNING")
    O("Rival", "id", _id([p("statement", S, True)]), src=OBJ + "; " + D4 + " (preregistration requires a strong rival)")
    O("Prediction", "id", _id([p("statement", S, True)]), src=OBJ + "; " + D4 + " (preregistration requires predictions)")
    O("Falsifier", "id", _id([p("statement", S, True)]), src=OBJ + "; " + D4 + " (preregistration requires falsifiers; immutable after PREREGISTERED)")
    O("Experiment", "id", _id([p("version", S, True, True), p("evidence_schema_ref", S, True), p("evaluator_ref", S, True), p("freeze_hash")]), [VRO],
      src=OBJ + "; " + D4 + " (evidence schema and evaluator required; a change after PREREGISTERED creates a new experiment version)")
    O("Metric", "id", _id([p("name", S, True)]), src=OBJ)
    O("Threshold", "id", _id([p("value", J, True)]), src=OBJ + "; " + D4 + " (changing a threshold after PREREGISTERED creates a new experiment version)",
      note="value is json: thresholds in protocol/thresholds.json are numbers and structural conditions")
    O("Evidence", "id", _id([p("payload_hash", S, True, True), p("git_commit", S, True, True), p("experiment_version", S, True, True), p("environment", S, True, True)]), [VRO, GB],
      src=OBJ + "; " + D4 + " (every authoritative evidence artifact binds to experiment version + commit + environment)")
    O("Verdict", "id", _id([p("value", S, True, True, [VERDICTS]), p("reason"), p("derivation_hash", S, True, True), p("git_commit", S, True, True)]), [VRO, GB],
      src=OBJ + "; " + D4 + " (a SUPPORTED verdict is machine-derived from frozen evidence/evaluator); AGENTS.md section 5 (verdict semantics); src/hdd/verdict.py (Verdict)",
      note="reason is the explicit INCONCLUSIVE/INVALID reason; derivation_hash binds the verdict to the evidence+evaluator it was derived from")
    O("Component", "id", _id([p("path", S, True), p("orphan_flagged", BO, True)]), src=OBJ + "; " + D4 + " (a component with no link to an active hypothesis is flagged as an orphan, not deleted)")
    O("ContractVersion", "id", _id([p("sha256", S, True, True), p("git_commit", S, True, True), p("frozen_at", DT)]), [VRO, GB],
      src=OBJ + "; protocol/FREEZE.json (frozen file hashes)", note="sha256/frozen_at mirror FREEZE.json protocol_sha256 / frozen_at")
    O("Commit", "sha", [p("sha", S, True, True), p("message"), p("committed_at", DT)], src=OBJ + "; " + D5 + " (Git = canonical authority)")
    O("Test", "id", _id([p("name", S, True), p("last_result", S, False, False, [enum("passed", "failed", "error")])]), src=OBJ)
    O("Decision", "id", _id([p("rationale", S, True), p("decided_at", DT)]), [VRO], src=OBJ + "; AGENTS.md section 6 (a material post-reveal change creates a new experiment version)",
      note="human or orchestrator decision that changes a ContractVersion")
    O("Failure", "id", _id([p("description", S, True)]), src=OBJ)


def add_links(b):
    L = b.link
    src = f"{D4} (Required links)"
    for lid, a, c, fc, tc in (
            ("HAS_RIVAL", "Hypothesis", "Rival", MANY, ONE), ("PREDICTS", "Hypothesis", "Prediction", MANY, ONE),
            ("FALSIFIED_BY", "Hypothesis", "Falsifier", MANY, ONE), ("TESTED_BY", "Hypothesis", "Experiment", MANY, ONE),
            ("MEASURES", "Experiment", "Metric", MANY, MANY), ("GOVERNED_BY", "Metric", "Threshold", MANY, MANY),
            ("PRODUCES", "Experiment", "Evidence", MANY, ONE), ("SUPPORTS_OR_REFUTES", "Evidence", "Hypothesis", ONE_MANY, MANY),
            ("EVALUATES", "Verdict", "Hypothesis", ONE, MANY), ("CAPTURED_AT", "Evidence", "Commit", ONE, MANY),
            ("EXISTS_FOR", "Component", "Hypothesis", MANY, MANY), ("VALIDATES", "Test", "Component", MANY, MANY),
            ("DETECTED_BY", "Failure", "Test", ONE_MANY, MANY), ("CHANGES", "Decision", "ContractVersion", ONE_MANY, MANY)):
        L(lid, a, c, fc, tc, src=src + f": {a} {lid} {c}",
          note="cardinality is a choice (the docs list the link, not its multiplicity); convention: from_cardinality = links per FROM instance, to_cardinality = links per TO instance")
    L("SUPERSEDED_BY", "Hypothesis", "Hypothesis", OPT1, OPT1, src=D4 + " (lifecycle: optionally SUPERSEDED by a new hypothesis/version)",
      note="the docs name the transition, not a link vocabulary; added so SUPERSEDED has a target")


def add_observations(b):
    b.observation("TestRunObserved", "Test", [p("outcome", S, True, True, [enum("passed", "failed", "error")]), p("duration_ms", I), p("git_commit", S, True, True)], "pytest",
                  src=D4 + " (Test, Failure DETECTED_BY Test); AGENTS.md section 7 (machine-readable evidence)", note="a test run as observed fact; bound to the commit it ran at")
    b.observation("GitCommitObserved", "Commit", [p("sha", S, True, True), p("committed_at", DT)], "git",
                  src=D5 + " (Git = canonical authority; a clean rebuild from Git reproduces the state)", note="a commit as observed from Git")


def add_functions(b):
    F = b.fn
    F("evidence_count", [param("hypothesis", ref("Hypothesis"))], I, ["SUPPORTS_OR_REFUTES"], "fn:evidence_count:v1",
      src="ontology/examples/project-domain-minimal.json (frozen example function); " + D4 + " (EVALUATED requires required evidence)",
      note="implementation pending; reference model: HypothesisState.evidence_count in src/hdd/project_lifecycle_reference.py")
    F("compute_freeze_hash", [param("experiment", ref("Experiment"))], S,
      ["Experiment.version", "Experiment.evidence_schema_ref", "Experiment.evaluator_ref", "MEASURES", "GOVERNED_BY", "Threshold.value"],
      "scripts/freeze_protocol.py", src=D4 + " (RUNNING requires a freeze hash); scripts/freeze_protocol.py (sha256 over the frozen files)",
      note="pure: hash of the frozen contract inputs")
    F("derive_verdict", [param("hypothesis", ref("Hypothesis"))], S,
      ["TESTED_BY", "PRODUCES", "SUPPORTS_OR_REFUTES", "Evidence.payload_hash", "Experiment.evaluator_ref", "Threshold.value", "GOVERNED_BY", "MEASURES"],
      "src/hdd/verdict.py:evaluate_common", src=D4 + " (a SUPPORTED verdict is machine-derived from frozen evidence/evaluator); src/hdd/verdict.py (evaluate_common precedence)",
      note="returns one of SUPPORTED/REJECTED/INCONCLUSIVE/INVALID; missing evidence can never default to SUPPORTED")
    F("find_orphan_components", [], lst(ref("Component")), ["Component", "EXISTS_FOR", "Hypothesis.phase"], "fn:find_orphan_components:v1",
      src=D4 + " (a component with no link to an active hypothesis is flagged as an orphan)", note="implementation pending; read-only: flagging is the Action flag_orphan_component")
    F("canonical_state_hash", [], S,
      ["Hypothesis", "Rival", "Prediction", "Falsifier", "Experiment", "Metric", "Threshold", "Evidence", "Verdict", "Component", "ContractVersion", "Commit", "Test", "Decision", "Failure"],
      "fn:canonical_state_hash:v1", src=D5 + " (property 1: a clean rebuild from Git reproduces the same canonical Project Ontology state hash)",
      note="implementation pending; reads every object type")
    F("is_legal_transition", [param("hypothesis", ref("Hypothesis")), param("target_phase", S)], BO, ["Hypothesis.phase"],
      "src/hdd/project_lifecycle_reference.py", src=D4 + " (Required executable lifecycle); src/hdd/project_lifecycle_reference.py (preregister/start/evaluate/supersede guards)",
      note="the independent transition model the Project Ontology must agree with")
