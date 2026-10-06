"""Neutral operational requirements for the Project (hypothesis-driven development) domain."""
from .dsl import *  # noqa: F401,F403

CONFIG = {"time_unit": "1 tick = 1 second of logical time",
          "evaluators": {"neutral:evidence-present-v1": "protocol_valid = hypothesis.freeze_hash is non-blank; "
                         "required_evidence_complete = sample_sufficient = support_hit = (evidence_count >= 1); reject_hit = false"},
          "note": "Round 2's evaluator is registered code reading committed git blobs. The neutral spec replaces it with the "
                  "explicit evaluator above; Experiment.evaluator_ref values not listed here make derive_verdict fail (INVALID)."}


def phase(h, *ps): return in_(field(h, "phase"), ps)


def hyp_all(of, *ps):
    return {"op": "all_have", "of": of, "type": "Hypothesis", "field": "phase", "values": list(ps), "nonempty": True}


def op(name, summary, inputs, pre, rules, effects, gated, outcome):
    return {"name": name, "summary": summary, "inputs": inputs, "preconditions": pre, "business_rules": rules,
            "effects": effects, "gated_inputs": gated, "immutable_after_authorization": gated, "idempotency": "required",
            "approval": None, "expected_outcome": outcome}


STALE = lambda of: {"id": "stale-write", "decision": "deny", "description":  # noqa: E731
                    "Deny when any target hypothesis already has a SUPERSEDED_BY link (a newer version exists).",
                    "when": {"op": "any_have_link", "of": of, "link": "SUPERSEDED_BY"}}
EPH = {"id": "ephemeral-state-never-canonical", "decision": "deny", "description":
       "Deny when any string input starts with 'ephemeral:' (ephemeral state must never become canonical).",
       "when": {"op": "any_input_prefix", "prefix": "ephemeral:"}}


def lc(h, new_phase, name):
    return {"kind": "update", "type": "Hypothesis", "key": h, "props": {"phase": lit(new_phase)}, "note": name}


def operations(ir_actions):
    by = {a["id"]: [ir_input(x) for x in a["inputs"]] for a in ir_actions}
    h = inp("hypothesis")
    th = read("hypotheses_of_threshold", threshold=inp("threshold"))
    ex = read("hypotheses_of_experiment", experiment=inp("experiment"))
    def legal_for(target):
        return {"id": "legal-lifecycle-transition", "decision": "deny", "description":
                f"Deny unless the transition current phase -> {target} is legal (DRAFT>PREREGISTERED>RUNNING>EVALUATED>SUPERSEDED).",
                "when": not_(read("is_legal_transition", hypothesis=h, target_phase=lit(target)))}
    return [
        op("create_hypothesis", "Create a DRAFT hypothesis from a claim.", by["create_hypothesis"],
           [rule("claim-nonblank", "claim is not blank", nonblank(inp("claim")))], [STALE(lit([])), EPH],
           [{"kind": "create", "type": "Hypothesis", "key": read("hypothesis_id_for_claim", claim=inp("claim")),
             "props": {"id": read("hypothesis_id_for_claim", claim=inp("claim")), "claim": inp("claim"), "phase": lit("DRAFT")}}],
           ["claim"], "A Hypothesis with the derived key exists with phase DRAFT."),
        op("edit_threshold", "Change a threshold value while every governed hypothesis is still DRAFT.", by["edit_threshold"],
           [rule("governed-hypotheses-draft", "at least one hypothesis is governed by the threshold and all are DRAFT",
                 hyp_all(th, "DRAFT"))],
           [{"id": "threshold-immutable-after-preregistration", "decision": "deny", "description":
             "Deny when any governing hypothesis (Threshold <-GOVERNED_BY- Metric <-MEASURES- Experiment <-TESTED_BY- Hypothesis, "
             "following NEW_VERSION_OF back to the first tested experiment) is not DRAFT.",
             "when": not_(hyp_all(th, "DRAFT"))}, STALE(th), EPH],
           [{"kind": "update", "type": "Threshold", "key": inp("threshold"), "props": {"value": inp("value")}}],
           ["threshold", "value"], "Threshold.value equals the new value."),
        op("preregister_hypothesis", "Freeze a complete DRAFT contract.", by["preregister_hypothesis"],
           [rule("phase-draft", "hypothesis phase is DRAFT", phase(h, "DRAFT")),
            rule("freeze-hash-present", "freeze_hash is not blank", nonblank(inp("freeze_hash")))],
           [{"id": "contract-complete", "decision": "deny", "description":
             "Deny unless contract_complete(hypothesis) (claim, >=1 rival, >=1 prediction, >=1 falsifier, and an experiment "
             "with non-blank evidence_schema_ref and evaluator_ref) and freeze_hash is not blank.",
             "when": not_(read("contract_complete", hypothesis=h))}, legal_for("PREREGISTERED"), STALE(h), EPH],
           [{"kind": "update", "type": "Hypothesis", "key": h, "props": {"phase": lit("PREREGISTERED"), "freeze_hash": inp("freeze_hash")}}],
           ["hypothesis", "freeze_hash"], "Hypothesis phase PREREGISTERED with the given freeze_hash."),
        op("new_experiment_version", "Create a new version of an experiment after preregistration (thresholds stay frozen).",
           by["new_experiment_version"],
           [rule("hypotheses-not-draft", "all hypotheses tested by the experiment are not DRAFT",
                 {"op": "all_have", "of": ex, "type": "Hypothesis", "field": "phase",
                  "values": ["PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED"], "nonempty": True})],
           [{"id": "new-version-must-be-new", "decision": "deny", "description":
             "Deny when an Experiment with the new id already exists (never overwrite a version).",
             "when": exists(read("new_experiment_id", experiment=inp("experiment")))},
            {"id": "historical-binding-preserved", "decision": "deny", "description":
             "Deny when a ContractVersion with the new contract-version id already exists.",
             "when": exists(read("existing_contract_version", experiment=inp("experiment"), contract_version=inp("contract_version")))},
            STALE(ex), EPH],
           [{"kind": "create", "type": "Experiment", "key": read("new_experiment_id", experiment=inp("experiment")),
             "props": {"version": read("new_experiment_version_number", experiment=inp("experiment")),
                       "evidence_schema_ref": field(inp("experiment"), "evidence_schema_ref"),
                       "evaluator_ref": field(inp("experiment"), "evaluator_ref")}},
            {"kind": "create", "type": "ContractVersion", "key": read("new_contract_version_id", experiment=inp("experiment"), contract_version=inp("contract_version")),
             "props": {"sha256": read("compute_freeze_hash", experiment=inp("experiment")), "git_commit": read("head_commit")}},
            {"kind": "link", "link_type": "NEW_VERSION_OF", "src": read("new_experiment_id", experiment=inp("experiment")), "dst": inp("experiment")}],
           ["experiment", "contract_version"], "New Experiment version, matching ContractVersion and NEW_VERSION_OF link exist; the old version is unchanged."),
        op("start_run", "Start running a preregistered hypothesis.", by["start_run"],
           [rule("phase-preregistered", "hypothesis phase is PREREGISTERED", phase(h, "PREREGISTERED")),
            rule("has-freeze-hash", "hypothesis has a non-blank freeze_hash", nonblank(field(h, "freeze_hash")))],
           [{"id": "running-requires-freeze-hash", "decision": "deny", "description": "Deny when the hypothesis freeze_hash is blank.",
             "when": not_(nonblank(field(h, "freeze_hash")))}, legal_for("RUNNING"), STALE(h), EPH],
           [lc(h, "RUNNING", "start")], ["hypothesis"], "Hypothesis phase RUNNING."),
        op("attach_evidence", "Attach version- and commit-pinned evidence to a RUNNING hypothesis.", by["attach_evidence"],
           [rule("phase-running", "hypothesis phase is RUNNING", phase(h, "RUNNING")),
            rule("evidence-pinned", "evidence has non-blank payload_hash, git_commit, experiment_version, environment AND its "
                 "experiment_version equals the version of exactly one experiment tested by the hypothesis",
                 read("evidence_pinned", hypothesis=h, evidence=inp("evidence")))],
           [{"id": "evidence-must-bind-version-commit-environment", "decision": "deny", "description":
             "Deny unless evidence_pinned(hypothesis, evidence).", "when": not_(read("evidence_pinned", hypothesis=h, evidence=inp("evidence")))},
            {"id": "historical-binding-preserved", "decision": "deny", "description":
             "Deny when an experiment that already PRODUCES the evidence has a version different from evidence.experiment_version.",
             "when": read("evidence_rebinding", evidence=inp("evidence"))}, STALE(h), EPH],
           [{"kind": "create", "type": "Evidence", "key": inp("evidence"), "upsert_same_props": True,
             "props": {k: field(inp("evidence"), k) for k in ("payload_hash", "git_commit", "experiment_version", "environment")}},
            {"kind": "link", "link_type": "PRODUCES", "src": read("evidence_experiment", hypothesis=h, evidence=inp("evidence")), "dst": inp("evidence")},
            {"kind": "link", "link_type": "SUPPORTS_OR_REFUTES", "src": inp("evidence"), "dst": h}],
           ["hypothesis", "evidence"], "PRODUCES and SUPPORTS_OR_REFUTES links exist; evidence_count(hypothesis) increased."),
        op("evaluate_hypothesis", "Machine-derive a verdict and mark the hypothesis EVALUATED.", by["evaluate_hypothesis"],
           [rule("phase-running", "hypothesis phase is RUNNING", phase(h, "RUNNING")),
            rule("evidence-or-reason", "evidence_count(hypothesis) >= 1 or derive_verdict(hypothesis) is INCONCLUSIVE/INVALID",
                 or_(ge(read("evidence_count", hypothesis=h), lit(1)), in_(read("derive_verdict", hypothesis=h), ["INCONCLUSIVE", "INVALID"])))],
           [{"id": "evaluated-requires-evidence-or-reason", "decision": "deny", "description":
             "Deny when evidence_count == 0 and derive_verdict is not INCONCLUSIVE/INVALID.",
             "when": and_(eq(read("evidence_count", hypothesis=h), lit(0)), not_(in_(read("derive_verdict", hypothesis=h), ["INCONCLUSIVE", "INVALID"])))},
            {"id": "verdict-machine-derived", "decision": "deny", "description":
             "The verdict value is always derive_verdict(hypothesis); callers cannot supply a verdict. Deny when derive_verdict "
             "does not yield one of SUPPORTED/REJECTED/INCONCLUSIVE/INVALID.",
             "when": not_(in_(read("derive_verdict", hypothesis=h), ["SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID"]))},
            legal_for("EVALUATED"), STALE(h), EPH],
           [{"kind": "create", "type": "Verdict", "key": read("next_verdict_id", hypothesis=h),
             "props": {"value": read("derive_verdict", hypothesis=h), "reason": read("verdict_reason", hypothesis=h),
                       "derivation_hash": read("verdict_derivation_hash", hypothesis=h), "git_commit": read("head_commit")}},
            lc(h, "EVALUATED", "evaluate"),
            {"kind": "link", "link_type": "EVALUATES", "src": read("next_verdict_id", hypothesis=h), "dst": h}],
           ["hypothesis"], "A Verdict whose value equals derive_verdict(hypothesis) exists and the hypothesis is EVALUATED."),
        op("supersede_hypothesis", "Replace an EVALUATED hypothesis by a successor.", by["supersede_hypothesis"],
           [rule("phase-evaluated", "hypothesis phase is EVALUATED", phase(h, "EVALUATED"))],
           [{"id": "conflicting-change", "decision": "deny", "description":
             "Deny when successor == hypothesis or the successor is already the SUPERSEDED_BY target of a different hypothesis.",
             "when": or_(eq(inp("successor"), h), {"op": "other_has_link_to", "link": "SUPERSEDED_BY", "dst": inp("successor"), "except": h})},
            legal_for("SUPERSEDED"), STALE(h), EPH],
           [lc(h, "SUPERSEDED", "supersede"), {"kind": "link", "link_type": "SUPERSEDED_BY", "src": h, "dst": inp("successor")}],
           ["hypothesis", "successor"], "Hypothesis SUPERSEDED with SUPERSEDED_BY -> successor."),
        op("record_decision", "Record a decision that changes a contract version.", by["record_decision"],
           [rule("rationale-nonblank", "the Decision's stored rationale is not blank", nonblank(field(inp("decision"), "rationale")))],
           [{"id": "historical-binding-preserved", "decision": "deny", "description":
             "Deny when the ContractVersion git_commit is blank (an unbound version cannot be changed by a decision).",
             "when": not_(nonblank(field(inp("contract_version"), "git_commit")))}, EPH],
           [{"kind": "create", "type": "Decision", "key": inp("decision"), "upsert_same_props": True,
             "props": {"rationale": field(inp("decision"), "rationale"), "decided_at": field(inp("decision"), "decided_at")}},
            {"kind": "link", "link_type": "CHANGES", "src": inp("decision"), "dst": inp("contract_version")}],
           ["decision", "contract_version"], "Decision and CHANGES link to the contract version exist."),
        op("flag_orphan_component", "Flag (never delete) a component with no active hypothesis.", by["flag_orphan_component"],
           [rule("component-is-orphan", "component is in find_orphan_components",
                 {"op": "in_read", "value": inp("component"), "read": read("find_orphan_components")})],
           [{"id": "orphan-flagged-not-deleted", "decision": "classify", "description":
             "Classification only: an orphan is flagged orphan_flagged=true and is never deleted by any operation.",
             "when": lit(True)}, STALE(lit([])), EPH],
           [{"kind": "update", "type": "Component", "key": inp("component"), "props": {"orphan_flagged": lit(True)}}],
           ["component"], "Component.orphan_flagged == true and the component still exists."),
    ]
