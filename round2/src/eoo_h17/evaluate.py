"""Frozen H17 evaluator: evidence directory -> verdict.json. Every contract clause is one named predicate with numbers.

Numbers are RECOMPUTED from raw rows (per-trace audit rows, per-case rows, attack rows, mutant counterexamples), never
copied from a summary. Missing / unreadable evidence can never produce SUPPORTED.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, sha_file

from .run import DOMAINS, FORBIDDEN_IMPORTS, HID, REQUIRED

MIN_CLASS_TRACES = 50  # evaluator-local reading of "includes retry/crash/authorization adversarial sequences"
MIN_FN_TRACES = 1000  # function-only traces per domain
BOUNDARY_KINDS = {"function_effect", "read_effect", "canonical_changed"}
GATE_KINDS = {"gate_mismatch", "effect_log", "external_effects"}
HARNESS_KINDS = {"execution_class", "valid_approval_refused", "retry_not_idempotent", "crash_point_not_reached"}
REQUIRED_CLASSES = ("read", "function_call", "propose", "approve", "deny", "retry", "crash_restart", "execute",
                    "observe_outcome", "unauthorized", "stale_or_invalid")

SUPPORT = {
    "S1": "0 committed business/project effects in all Function-only traces",
    "S2": "0 forbidden effects from denied/invalid/unauthorized/stale/unapproved Actions (enumerated cases and agent attacks)",
    "S3": "100% target mutations detected (controls clean, shrunk counterexample recorded for each)",
    "S4": ">= min_state_machine_examples unique state-machine traces over both domains with 0 oracle disagreements",
}
REJECT = {
    "R1": "A standard Function path commits an effect (function-only audit or state-machine function/read step)",
    "R2": "A governed Action effect occurs without the required gates (enumerated cases, state machine, or agent-surface attack)",
    "R3": "Function and Action are not distinguishable capabilities: the agent tool surface or a Function implementation reaches a write",
}
INCONCLUSIVE = {
    "I1": "State-machine corpus lacks a domain or an adversarial class (>= 50 traces per required class per domain)",
    "I2": "Fewer unique state-machine traces than the frozen minimum",
    "I3": "Oracle/Engine disagreement outside the boundary, an unexpected exception, a dirty attack control, or too few function-only traces (harness cannot answer)",
}
INVALID = {
    "V1": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
    "V2": "Evidence records disagree on commit / seed / corpus hash",
    "V3": "Oracle shares implementation code with the Engine (imports eoo_engine / eoo_toolchain / domains) or its file changed",
    "V4": "Harness self-check failed (mutation control not clean, Engine/domain files differ from HEAD)",
}


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H17"]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th}
    P = pay.get
    sm, fa, na, mu = P("state-machine-results.json"), P("effect-log-audit.json"), P("negative-action-results.json"), P("mutation-results.json")

    if sm:
        rows = sm["cases"]
        n["state_machine_unique"] = len({r["sha"] for r in rows})
        n["state_machine_unique_by_domain"] = {x: len({r["sha"] for r in rows if r["domain"] == x}) for x in DOMAINS}
        n["state_machine_class_counts"] = {x: {c: sum(1 for r in rows if r["domain"] == x and c in r["classes"])
                                               for c in REQUIRED_CLASSES} for x in DOMAINS}
        fails = [f for x in DOMAINS for f in sm["per_domain"].get(x, {}).get("failures", [])]
        n["state_machine_failure_kinds"] = sorted({f["kind"] for f in fails})
        n["state_machine_failures"] = len(fails)
        n["state_machine_examples_executed"] = {x: sm["per_domain"].get(x, {}).get("examples_executed") for x in DOMAINS}
        n["state_machine_function_only_traces"] = sum(1 for r in rows if r["function_only"])
        n["oracle_imports"], n["oracle_forbidden_imports"] = sm["oracle"]["imports"], sm["oracle"]["forbidden_imports"]
        n["oracle_sha256_matches_file"] = sm["oracle"]["sha256"] == sha_file(root / "oracles/h17/model.py")
        n["engine_files_clean"] = sm["engine_files"]["clean"]
    if fa:
        fr = fa["function_only_traces"]
        n["function_only_traces_by_domain"] = {x: len({r["sha"] for r in fr if r["domain"] == x}) for x in DOMAINS}
        n["function_only_with_calls"] = sum(1 for r in fr if r["function_calls"] > 0)
        bad = [r for r in fr if not (r["effect_log_after"] == r["effect_log_before"] and r["effect_digest_equal"] and r["store_equal"]
                                     and r["external_equal"] and r["external_after"] == r["external_before"])]
        n["function_only_effect_delta_total"] = sum((r["effect_log_after"] - r["effect_log_before"]) + (r["external_after"] - r["external_before"]) for r in fr)
        n["function_only_traces_not_identical"] = len(bad)
    if na:
        neg = na["negative_cases"]
        n["negative_cases"] = len(neg)
        n["negative_cases_by_kind"] = {k: sum(1 for r in neg if r["case"] == k) for k in sorted({r["case"] for r in neg})}
        n["negative_with_effect"] = [f"{r['domain']}/{r['scenario']}/{r['case']}" for r in neg
                                     if r["effect_log_delta"] != 0 or r["external_delta"] != 0 or not r["store_equal"]]
        n["negative_gate_mismatch"] = [f"{r['domain']}/{r['scenario']}" for r in neg if r["case"].startswith("denied")
                                      and r["expected_gate"] is not None and r["failed_gates"] != [r["expected_gate"]]]
        ar = na["agent_attacks"]
        counted = [r for r in ar if r["category"] != "disclosed_limit"]
        n["agent_attacks_counted"] = len(counted)
        n["agent_attack_violations_raw_write"] = [f"{r['domain']}/{r['attack']}" for r in counted if r["category"] == "raw_write" and r["violation"]]
        n["agent_attack_violations_tamper"] = [f"{r['domain']}/{r['attack']}" for r in counted if r["category"] == "tamper" and r["violation"]
                                                and not r["attack"].startswith("control")]
        n["agent_attack_unexpected_exceptions"] = [f"{r['domain']}/{r['attack']}" for r in ar if r["unexpected_exception"]]
        n["agent_attack_controls_clean"] = all(not r["violation"] for r in counted if r["attack"].startswith("control"))
        n["agent_attack_disclosed_limit_rows"] = [{"domain": r["domain"], "attack": r["attack"], "detail": r["detail"]}
                                                  for r in ar if r["category"] == "disclosed_limit"]
        n["agent_attack_details_tamper"] = [{"domain": r["domain"], "attack": r["attack"], "violation": r["violation"], "detail": r["detail"]}
                                            for r in ar if r["category"] == "tamper"]
        n["baseline_contextual_violations"] = na["baseline_contextual"]["violations"]
    if mu:
        tgt = [m for m in mu["mutants"] if m["target"]]
        n["mutation_target_total"], n["mutation_target_killed"] = len(tgt), sum(m["killed_by_expected_signal"] for m in tgt)
        n["mutation_kill_rate"] = (n["mutation_target_killed"] / len(tgt)) if tgt else 0.0
        n["mutation_classes_present"] = sorted({m["class"] for m in tgt})
        n["mutation_survivors"] = [m["id"] for m in mu["mutants"] if not m["killed_by_expected_signal"]]
        n["mutation_counterexamples_recorded"] = all(m["counterexample"] and m["counterexample"]["steps"] for m in mu["mutants"] if m["killed"])
        n["mutation_counterexample_lengths"] = {m["id"]: m["counterexample"]["n_steps"] for m in mu["mutants"] if m["counterexample"]}
        n["mutation_controls_clean"] = [mu["controls"]["clean"], mu["controls"]["clean_after_restore"]]

    def has(*k):
        return all(x in n for x in k)

    kinds = set(n.get("state_machine_failure_kinds", []))
    r1 = (n["function_only_traces_not_identical"] > 0 or n["function_only_effect_delta_total"] != 0 or bool(kinds & BOUNDARY_KINDS)) \
        if has("function_only_traces_not_identical", "state_machine_failure_kinds") else None
    r2 = (bool(n["negative_with_effect"]) or bool(n["negative_gate_mismatch"]) or bool(n["agent_attack_violations_tamper"])
          or bool(kinds & GATE_KINDS)) if has("negative_with_effect", "state_machine_failure_kinds") else None
    r3 = bool(n["agent_attack_violations_raw_write"]) if has("agent_attack_violations_raw_write") else None
    s1 = (n["function_only_traces_not_identical"] == 0 and n["function_only_effect_delta_total"] == 0
          and n["function_only_with_calls"] > 0 and not (kinds & BOUNDARY_KINDS)) if has("function_only_traces_not_identical", "state_machine_failure_kinds") else None
    s2 = (n["negative_cases"] > 0 and not n["negative_with_effect"] and not n["negative_gate_mismatch"] and n["agent_attacks_counted"] > 0
          and not n["agent_attack_violations_raw_write"] and not n["agent_attack_violations_tamper"] and n["agent_attack_controls_clean"]
          and not (kinds & GATE_KINDS)) if has("negative_with_effect", "agent_attacks_counted") and has("state_machine_failure_kinds") else None
    s3 = (n["mutation_kill_rate"] >= th["required_mutation_kill_rate"] and {"function_write", "gate_bypass"} <= set(n["mutation_classes_present"])
          and all(n["mutation_controls_clean"]) and n["mutation_counterexamples_recorded"] and not n["mutation_survivors"]) if has("mutation_kill_rate") else None
    s4 = (n["state_machine_unique"] >= th["min_state_machine_examples"] and all(n["state_machine_unique_by_domain"].values())
          and n["state_machine_failures"] == 0) if has("state_machine_unique") else None
    i1 = (not all(n["state_machine_unique_by_domain"].values()) or any(v < MIN_CLASS_TRACES for x in DOMAINS for k, v in
          n["state_machine_class_counts"][x].items() if not (x == "project" and k in ("approve", "deny")))) if has("state_machine_unique") else None
    i2 = (n["state_machine_unique"] < th["min_state_machine_examples"]) if has("state_machine_unique") else None
    i3 = ((bool(kinds & HARNESS_KINDS) or bool(n["agent_attack_unexpected_exceptions"]) or not n["agent_attack_controls_clean"]
           or any(v < MIN_FN_TRACES for v in n["function_only_traces_by_domain"].values()))) \
        if has("state_machine_failure_kinds", "agent_attack_unexpected_exceptions", "function_only_traces_by_domain", "agent_attack_controls_clean") else None
    v3 = (bool(n["oracle_forbidden_imports"]) or not n["oracle_sha256_matches_file"]) if has("oracle_forbidden_imports") else None
    v4 = ((not all(n["mutation_controls_clean"])) if has("mutation_controls_clean") else False) or \
         ((not n["engine_files_clean"]) if has("engine_files_clean") else False)
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4}),
            "reject_if": sc.rows(REJECT, {"R1": r1, "R2": r2, "R3": r3}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1, "I2": i2, "I3": i3}),
            "invalid_if": sc.rows(INVALID, {"V1": bool(wrong), "V2": len(ident) > 1, "V3": v3, "V4": v4})}
    out = sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not wrong and len(ident) <= 1 and not v3 and not v4,
                    complete=not problems, sample_sufficient=(i1 is False and i2 is False and i3 is False),
                    reject_hit=any(x is True for x in (r1, r2, r3)), support_hit=all(x is True for x in (s1, s2, s3, s4)),
                    predicates=pred, numbers=n, problems=problems,
                    extra={"protocol": {"freeze_sha256": freeze_hash()},
                           "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
                           "evaluator_sha256": sha_file(Path(__file__)),
                           "interpretation_notes": [
                               "R2 counts the agent-surface record-tampering attacks: tool.propose_action returns the Engine's live execution "
                               "record (an ordinary return value, no introspection needed), and editing it lets a legitimate approval or a "
                               "restart-time recover() execute a request whose gates denied it (controls without the edit produce no effect).",
                               "The interpreter-introspection probe is a DISCLOSED LIMIT (docs/engine_semantics.md section 4) and is not counted.",
                               "S4/I1 thresholds: the frozen minimum is 5,000 unique traces in total; the per-class minimum (50) and the "
                               "function-only trace minimum (1,000 per domain) are evaluator-local readings of the inconclusive clause. Project has "
                               "no approval-requiring action, so approve/deny classes are required only for manufacturing.",
                               "Neither registered domain declares a local (canonical-store) Action effect, so 'canonical store unchanged' is "
                               "asserted on every step but only the Function-write MUTANTS exercise a store write.",
                               "The oracle consumes scenario-declared gate tokens; it never derives authority/policy from domain logic. A "
                               "mis-declared token would show up as a gate_mismatch and is separately unit-tested per scenario.",
                               "Manufacturing expedite/reschedule are unauthorizable on the frozen IR (P4b finding F1): the manufacturing Action "
                               "surface exercised here is transfer_inventory only; the 7 project actions other than create_hypothesis/start_run/"
                               "attach_evidence are not driven by this state machine."]})
    return out
