"""Project-domain read operations (IR functions), helpers, unsupported items, invariants and the synthetic seed."""
from .dsl import *  # noqa: F401,F403


def reads(ir_funcs):
    by = {f["id"]: [ir_input(x) for x in f["inputs"]] for f in ir_funcs}
    return [
        {"name": "evidence_count", "inputs": by["evidence_count"], "output": "integer",
         "description": "Number of Evidence resources with a SUPPORTS_OR_REFUTES link to the hypothesis."},
        {"name": "compute_freeze_hash", "inputs": by["compute_freeze_hash"], "output": "string",
         "description": "NEUTRAL stand-in (not byte-identical to Round 2, which hashed committed git blobs): lowercase hex sha256 of "
         "the canonical JSON (sorted keys, no spaces) of {evidence_schema_ref, evaluator_ref, thresholds: [[threshold key, value], ...]} "
         "where thresholds are those reachable Experiment -MEASURES-> Metric -GOVERNED_BY-> Threshold, sorted by key, de-duplicated."},
        {"name": "derive_verdict", "inputs": by["derive_verdict"], "output": "string",
         "description": "Pack-wide precedence over five booleans (protocol_valid, required_evidence_complete, sample_sufficient, "
         "reject_hit, support_hit): not protocol_valid -> INVALID; reject_hit -> REJECTED; incomplete evidence or insufficient sample -> "
         "INCONCLUSIVE; support_hit -> SUPPORTED; else INCONCLUSIVE. Booleans: latest experiment = highest version (numeric if "
         "numeric) among experiments TESTED_BY the hypothesis; none -> (valid, incomplete, insufficient, no reject, no support); evidence = "
         "Evidence PRODUCED by it whose experiment_version equals its version; none -> protocol_valid = freeze_hash non-blank, "
         "everything else false; otherwise the evaluator named by Experiment.evaluator_ref (config.evaluators) yields the booleans and "
         "protocol_valid is further ANDed with freeze_hash non-blank. Unknown evaluator_ref -> error (operation fails closed)."},
        {"name": "find_orphan_components", "inputs": [], "output": "list",
         "description": "Sorted keys of Components with no EXISTS_FOR link to a hypothesis whose phase is not SUPERSEDED."},
        {"name": "canonical_state_hash", "inputs": [], "output": "string",
         "description": "sha256 hex of the canonical JSON of the sorted list of [type, key, props] over every resource of the 15 "
         "project resource types (rows sorted by (type, str(key)))."},
        {"name": "is_legal_transition", "inputs": by["is_legal_transition"], "output": "boolean",
         "description": "True iff target_phase is the phase immediately after the hypothesis' current phase in "
         "DRAFT > PREREGISTERED > RUNNING > EVALUATED > SUPERSEDED (other conditions are checked elsewhere)."},
    ]


def _h(name, ins, out, desc): return {"name": name, "inputs": ins, "output": out, "description": desc}


HELPERS = [
    _h("hypothesis_id_for_claim", [i("claim", "string")], "string", "'hyp-' + first 10 hex chars of sha256(UTF-8 claim)."),
    _h("hypotheses_of_experiment", [i("experiment", "resource", True, "Experiment")], "list",
       "Hypotheses linked TESTED_BY to the experiment; if none, follow NEW_VERSION_OF to the predecessor and repeat (cycle-safe)."),
    _h("hypotheses_of_threshold", [i("threshold", "resource", True, "Threshold")], "list",
       "Union (first-seen order) of hypotheses_of_experiment over Experiments MEASURES-linked to Metrics GOVERNED_BY the threshold."),
    _h("contract_complete", [i("hypothesis", "resource", True, "Hypothesis")], "boolean",
       "claim non-blank AND >=1 HAS_RIVAL AND >=1 PREDICTS AND >=1 FALSIFIED_BY AND some TESTED_BY experiment with non-blank "
       "evidence_schema_ref and evaluator_ref."),
    _h("new_experiment_version_number", [i("experiment", "resource", True, "Experiment")], "string",
       "version+1 if version is all digits, else version + '.1'."),
    _h("new_experiment_id", [i("experiment", "resource", True, "Experiment")], "string",
       "(experiment key split at '@v', first part) + '@v' + new_experiment_version_number."),
    _h("new_contract_version_id", [i("experiment", "resource", True, "Experiment"), i("contract_version", "resource", True, "ContractVersion")],
       "string", "contract_version key + '+' + new_experiment_version_number."),
    _h("existing_contract_version", [i("experiment", "resource", True, "Experiment"), i("contract_version", "resource", True, "ContractVersion")],
       "string|null", "new_contract_version_id if a ContractVersion with that key exists, else null."),
    _h("head_commit", [], "string", "Key of the Commit with the greatest committed_at (ties: greatest key); error if none."),
    _h("evidence_experiment", [i("hypothesis", "resource", True, "Hypothesis"), i("evidence", "resource", True, "Evidence")], "string|null",
       "The single experiment TESTED_BY the hypothesis whose version equals evidence.experiment_version; null if zero or several."),
    _h("evidence_pinned", [i("hypothesis", "resource", True, "Hypothesis"), i("evidence", "resource", True, "Evidence")], "boolean",
       "evidence exists, payload_hash/git_commit/experiment_version/environment are all non-blank, and evidence_experiment is non-null."),
    _h("evidence_rebinding", [i("evidence", "resource", True, "Evidence")], "boolean",
       "Some Experiment already PRODUCES the evidence and has version != evidence.experiment_version."),
    _h("next_verdict_id", [i("hypothesis", "resource", True, "Hypothesis")], "string",
       "'verdict-' + hypothesis key + '-' + (number of Verdicts already EVALUATES-linked to it + 1)."),
    _h("verdict_reason", [i("hypothesis", "resource", True, "Hypothesis")], "string",
       "Human-readable text naming the experiment, the evidence count and the five booleans used by derive_verdict."),
    _h("verdict_derivation_hash", [i("hypothesis", "resource", True, "Hypothesis")], "string",
       "sha256 hex of canonical JSON of {hypothesis, experiment [key, version, evaluator_ref] or null, evidence [[key, payload_hash]] sorted, "
       "booleans, freeze_hash}."),
]
UNSUPPORTED = []
EXCLUDED_TYPES = {}
INVARIANTS = [
    {"id": "supported-needs-evidence", "text": "A SUPPORTED verdict implies evidence_count >= 1", "ir": "supported-needs-evidence"},
    {"id": "preregistration-complete-contract", "text": "A non-DRAFT hypothesis has a complete contract", "ir": "preregistration-complete-contract"},
    {"id": "threshold-immutable-after-preregistration", "text": "Threshold values of a non-DRAFT hypothesis never change", "ir": "threshold-immutable-after-preregistration"},
    {"id": "falsifier-immutable-after-preregistration", "text": "Falsifier statements of a non-DRAFT hypothesis never change", "ir": "falsifier-immutable-after-preregistration"},
    {"id": "evaluator-immutable-after-preregistration", "text": "Experiment evaluator_ref/evidence_schema_ref of a non-DRAFT hypothesis never change in place (a new version is created instead)", "ir": "evaluator-immutable-after-preregistration"},
    {"id": "running-requires-freeze-hash", "text": "A RUNNING (or later) hypothesis has a non-blank freeze_hash", "ir": "running-requires-freeze-hash"},
    {"id": "evaluated-requires-evidence-or-reason", "text": "EVALUATED needs evidence or an INCONCLUSIVE/INVALID verdict", "ir": "evaluated-requires-evidence-or-reason"},
    {"id": "verdict-machine-derived", "text": "Verdict.value always equals derive_verdict at evaluation time; no direct verdict writes", "ir": "verdict-machine-derived"},
    {"id": "verdict-vocabulary", "text": "Verdict.value in {SUPPORTED, REJECTED, INCONCLUSIVE, INVALID}", "ir": "verdict-vocabulary"},
    {"id": "evidence-bound-to-version-commit-environment", "text": "Attached evidence is pinned to an experiment version, commit and environment", "ir": "evidence-bound-to-version-commit-environment"},
    {"id": "orphan-component-flagged-not-deleted", "text": "Components are flagged, never deleted", "ir": "orphan-component-flagged-not-deleted"},
    {"id": "lifecycle-order", "text": "Phase order DRAFT > PREREGISTERED > RUNNING > EVALUATED > SUPERSEDED, no skipping, no going back", "ir": "lifecycle-order"},
    {"id": "no-silent-stale-write", "text": "A write targeting a superseded hypothesis is rejected, never silently applied", "ir": "no-silent-stale-write"},
    {"id": "conflicts-surface-explicitly", "text": "A conflicting supersede is denied with an explicit conflict", "ir": "conflicts-surface-explicitly"},
    {"id": "ephemeral-state-marked", "text": "Inputs marked 'ephemeral:' never become canonical state", "ir": "ephemeral-state-marked"},
    {"id": "historical-binding-preserved", "text": "Existing evidence/version/contract bindings are never rewritten", "ir": "historical-binding-preserved"},
    {"id": "durable-actions-are-git-changes", "text": "Every durable change is a canonical-store write made by an authorized operation (no side channel)", "ir": "durable-actions-are-git-changes"},
    {"id": "rebuild-reproduces-state-hash", "text": "Rebuilding the canonical state from its stored rows reproduces canonical_state_hash", "ir": "rebuild-reproduces-state-hash"},
]
EXCLUDED_CONSTRAINTS = {}


def _o(t, k, **p): return {"type": t, "key": k, "props": {"id" if t != "Commit" else "sha": k, **p}}
def _l(t, s, d): return {"link_type": t, "src": s, "dst": d}


def seed():
    ev = "neutral:evidence-present-v1"
    objs = [
        _o("Hypothesis", "H-A", claim="draft claim A", phase="DRAFT"),
        _o("Hypothesis", "H-B", claim="prereg claim B", phase="PREREGISTERED", freeze_hash="f" * 64),
        _o("Hypothesis", "H-C", claim="running claim C", phase="RUNNING", freeze_hash="e" * 64),
        _o("Hypothesis", "H-D", claim="evaluated claim D", phase="EVALUATED", freeze_hash="d" * 64),
        _o("Hypothesis", "H-E", claim="successor claim E", phase="DRAFT"),
        _o("Hypothesis", "H-F", claim="running claim F (no evidence yet)", phase="RUNNING", freeze_hash="c" * 64),
    ]
    links = []
    for h in "ABCDF":
        for kind, lt, n in (("Rival", "HAS_RIVAL", "R"), ("Prediction", "PREDICTS", "P"), ("Falsifier", "FALSIFIED_BY", "X")):
            k = f"{n}-{h}"
            objs.append(_o(kind, k, statement=f"{kind.lower()} for {h}"))
            links.append(_l(lt, f"Hypothesis:H-{h}", f"{kind}:{k}"))
        e = f"E-{h}@v1"
        objs += [_o("Experiment", e, version="1", evidence_schema_ref="schemas/evidence.json", evaluator_ref=ev),
                 _o("Metric", f"M-{h}", name=f"metric {h}"), _o("Threshold", f"T-{h}", value={"min": 10})]
        links += [_l("TESTED_BY", f"Hypothesis:H-{h}", f"Experiment:{e}"), _l("MEASURES", f"Experiment:{e}", f"Metric:M-{h}"),
                  _l("GOVERNED_BY", f"Metric:M-{h}", f"Threshold:T-{h}")]
    objs += [_o("Commit", "c0ffee0001", message="seed head", committed_at=100),
             _o("Commit", "c0ffee0000", message="seed base", committed_at=50)]
    for k, h, exp, att in (("EV-C1", "C", "E-C@v1", True), ("EV-C2", "C", "E-C@v1", False), ("EV-D1", "D", "E-D@v1", True),
                           ("EV-C-BAD", "C", "9", False)):
        objs.append(_o("Evidence", k, payload_hash=f"{k}-hash", git_commit="c0ffee0001", experiment_version=exp.split("@v")[-1] if "@v" in exp else exp,
                       environment="seed-env"))
        links.append(_l("CAPTURED_AT", f"Evidence:{k}", "Commit:c0ffee0001"))
        if att:
            links += [_l("PRODUCES", f"Experiment:{exp}", f"Evidence:{k}"), _l("SUPPORTS_OR_REFUTES", f"Evidence:{k}", f"Hypothesis:H-{h}")]
    objs += [_o("Verdict", "verdict-H-D-1", value="SUPPORTED", reason="seed", derivation_hash="0" * 64, git_commit="c0ffee0001")]
    links.append(_l("EVALUATES", "Verdict:verdict-H-D-1", "Hypothesis:H-D"))
    objs += [_o("Component", "cmp-live", path="src/live", orphan_flagged=False), _o("Component", "cmp-orphan", path="src/orphan", orphan_flagged=False),
             _o("Test", "t-1", name="live test", last_result="passed"), _o("Failure", "f-1", description="seed failure"),
             _o("ContractVersion", "CV-1", sha256="1" * 64, git_commit="c0ffee0001"),
             _o("ContractVersion", "CV-UNBOUND", sha256="2" * 64, git_commit=""),
             _o("Decision", "DEC-1", rationale="keep the threshold", decided_at=90),
             _o("Decision", "DEC-BLANK", rationale="  ", decided_at=91)]
    links += [_l("EXISTS_FOR", "Component:cmp-live", "Hypothesis:H-B"), _l("VALIDATES", "Test:t-1", "Component:cmp-live"),
              _l("DETECTED_BY", "Failure:f-1", "Test:t-1")]
    return {"objects": objs, "links": links}
