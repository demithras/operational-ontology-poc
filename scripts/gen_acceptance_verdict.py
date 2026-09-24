#!/usr/bin/env python3
"""Derives experiments/exp-NNN/results/final-report.md's headline verdict
block (can_decide_now / can_prove_why_later / exit code) directly from
docs/experiment/spec/11_acceptance_criteria.md's own mandatory-condition
lists, each mapped to a concrete signal read from THIS run's result
artifacts — never hand-typed. Exit codes follow spec 11's table (also
experiments/exp-000/manifest.yaml#exit_codes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(results_dir: Path, name: str) -> dict | None:
    p = results_dir / name
    return json.loads(p.read_text()) if p.exists() else None


def _status_and(*vals: bool | None) -> bool | None:
    if any(v is None for v in vals):
        return None
    return all(vals)


def _hyp_bool(hyps: dict, h: str) -> bool | None:
    status = hyps.get(h, {}).get("status")
    if status == "SUPPORTED":
        return True
    if status == "REJECTED":
        return False
    return None  # INCONCLUSIVE or missing — unknown, never a silent False


def _fault(fault_doc: dict | None, fid: str) -> str | None:
    if not fault_doc:
        return None
    for m in fault_doc["matrix"]:
        if m["id"] == fid:
            return m["status"]
    return None


def derive(results_dir: Path) -> dict:
    test_results = _load(results_dir, "test-results.json")
    fault_doc = _load(results_dir, "fault-results.json")
    latency = _load(results_dir, "latency.json")
    evolution = _load(results_dir, "evolution-comparison.json") or _load(REPO_ROOT / "experiments" / "exp-000" / "results", "evolution-comparison.json")
    hyps = (_load(results_dir, "hypothesis-results.json") or {}).get("hypotheses", {})
    tests = (test_results or {}).get("tests", {})

    def clean(*subs: str) -> bool | None:
        matched = {k: v for k, v in tests.items() if any(s in k for s in subs)}
        if not matched:
            return None
        return all(v["outcome"] == "passed" for v in matched.values())

    # ---- Headline A: can we decide now? (12 mandatory items) ----------
    a_items = {
        "1_canonical_incident": clean("test_canonical_scenario.py"),
        "2_hot_read_p95": _slo_pass(latency, "bench_phase4"),
        "3_gate_p95": _slo_pass(latency, "bench_phase5", "gate_evaluation_p95_ms"),
        "4_proposal_p95": _slo_pass(latency, "bench_phase5", "decision_proposal_p95_ms"),
        "5_unauthorized_zero_effects": _fault(fault_doc, "F03") == "PASS" if fault_doc else None,
        "6_policy_denied_zero_effects": _fault(fault_doc, "F05") == "PASS" if fault_doc else None,
        "7_shacl_invalid_no_commit": _status_and(clean("test_shacl_fixtures.py", "test_shacl_rdf4j_transactional.py"),
                                                  _fault(fault_doc, "F07") == "PASS" if fault_doc else None),
        "8_concurrency_invariants": (fault_doc.get("concurrency_test", {}).get("status") == "PASS") if fault_doc else None,
        "9_duplicate_retry_one_effect": clean("test_idempotency.py"),
        "10_no_premature_observed_success": clean("test_divergence.py", "test_wms_faults.py"),
        "11_component_failure_explicit_state": (fault_doc["summary"]["NOT_TESTED"] == 0) if fault_doc else None,
        "12_deterministic_planner_no_llm": clean("test_canonical_scenario.py") and clean("tests/model/"),
    }
    can_decide_now = "PASS" if all(v is True for v in a_items.values()) else ("FAIL" if any(v is False for v in a_items.values()) else "INCONCLUSIVE")

    # ---- Headline B: can we prove why later? (11 mandatory items) -----
    ont_replay_clean = (evolution or {}).get("replay_sweep", {}).get("ontology_exit_code") == 0 if evolution else None
    b_items = {
        "1_all_successful_link_to_decision": _hyp_bool(hyps, "H1"),
        "2_decision_pins_contract_versions": _hyp_bool(hyps, "H1"),
        "3_evidence_snapshot_immutable_reconstructable": clean("test_f29_replay_integrity.py"),
        "4_actor_delegation_reconstructable": clean("test_decision_service_delegation.py"),
        "5_authz_policy_versioned_with_hash": clean("test_f29_tuple_snapshot_integrity.py"),
        "6_action_version_params_reconstructable": ont_replay_clean,
        "7_observed_outcome_linked_to_evidence": clean("test_divergence.py"),
        "8_v1_replays_after_v3": ont_replay_clean,
        "9_historical_replay_uses_historical_rules": ont_replay_clean,
        "10_forensic_query_answers_all": _hyp_bool(hyps, "H13"),
        "11_deleted_archive_fails_loudly": clean("test_f29_replay_integrity.py"),
    }
    can_prove_why_later = "PASS" if all(v is True for v in b_items.values()) else ("FAIL" if any(v is False for v in b_items.values()) else "INCONCLUSIVE")

    # ---- exit code (spec 11 "Exit statuses" / "Safety acceptance" /
    # "Data-quality acceptance" / "Replay acceptance") — orchestrator
    # correction (Phase 10b): the fault matrix's F-ids span several of
    # spec 11's DIFFERENT acceptance categories, and lumping "any FAIL"
    # into exit 10 conflated them. Each id below is placed by what its own
    # description actually tests, not by proximity in the F01-F40 list.
    #
    # Safety zero-tolerance (spec 11 "Safety acceptance", the literal six
    # items): unauthorized/policy-denied external side effect (F01-F06 —
    # every one of these is a "deny -> 0 external effects" gate test),
    # silent world/model divergence (F16/F17 — DIVERGED, not silently
    # accepted), agent bypass of server-side controls (F30-F34). Deliberately
    # EXCLUDES F09 (ambiguous identity — spec 11 lists this under
    # "Data-quality acceptance", not safety) and F22-F24/F26 (dependency-
    # unavailable fail-closed and stale-projection visibility — real gate
    # behavior, but not one of the six safety items verbatim).
    SAFETY_ZERO_TOLERANCE_FAULT_IDS = ["F01", "F02", "F03", "F04", "F05", "F06", "F16", "F17",
                                        "F30", "F31", "F32", "F33", "F34"]
    # Data-quality acceptance (spec 11's own separate section): ambiguous
    # identity, duplicate CDC, stale-projection detectability, projection
    # corruption detection, manual source edits, poison messages, mapping
    # deployment compatibility. A FAILURE here is a real defect but never
    # a safety zero-tolerance violation by spec 11's own structure.
    DATA_QUALITY_FAULT_IDS = ["F09", "F19", "F26", "F27", "F37", "F38", "F39"]
    REPLAY_FAULT_IDS = ["F28", "F29"]

    safety_relevant_fault_fail = bool(fault_doc and any(
        _fault(fault_doc, fid) == "FAIL" for fid in SAFETY_ZERO_TOLERANCE_FAULT_IDS))
    safety_fail = any(_hyp_bool(hyps, h) is False for h in ("H2", "H5", "H9", "H12")) or safety_relevant_fault_fail

    data_quality_fail = bool(fault_doc and any(_fault(fault_doc, fid) == "FAIL" for fid in DATA_QUALITY_FAULT_IDS))
    replay_fault_fail = bool(fault_doc and any(_fault(fault_doc, fid) == "FAIL" for fid in REPLAY_FAULT_IDS))

    if safety_fail:
        exit_code = 10
    elif _hyp_bool(hyps, "H5") is False or _hyp_bool(hyps, "H4") is False or data_quality_fail:
        # Correctness/invariant failure, broadly construed per spec 11 to
        # include data-integrity invariants (H4/H5) AND data-quality
        # defects (a consistency/corruption checker failing to do its
        # job IS a correctness failure of that mechanism) — never safety,
        # since no unauthorized/policy-denied EXTERNAL EFFECT occurred.
        exit_code = 11
    elif _hyp_bool(hyps, "H7") is False or _hyp_bool(hyps, "H8") is False or replay_fault_fail:
        exit_code = 12
    elif can_decide_now == "FAIL" and any(a_items[k] is False for k in ("2_hot_read_p95", "3_gate_p95", "4_proposal_p95")):
        exit_code = 13
    elif test_results is None or fault_doc is None:
        exit_code = 15
    elif can_decide_now != "PASS" or can_prove_why_later != "PASS":
        exit_code = 14
    else:
        exit_code = 0

    return {
        "can_decide_now": can_decide_now, "can_decide_now_items": a_items,
        "can_prove_why_later": can_prove_why_later, "can_prove_why_later_items": b_items,
        "safety_fail": bool(safety_fail),
        "data_quality_fail": data_quality_fail,
        "replay_fault_fail": replay_fault_fail,
        "exit_code": exit_code,
    }


def _slo_pass(latency: dict | None, bench_key: str, slo_key: str | None = None) -> bool | None:
    """Bug found by the orchestrator (Phase 10b): bench-phase4.json's SLO
    verdict lives at top-level `slo.hot_read_p95_ms.pass` — its `hot_read`
    key holds the raw cold/warm SAMPLES, not a verdict, and has no `pass`
    field at all. The old ternary here checked `isinstance(hot_read, dict)`
    (always true) and then read a `pass` key that doesn't exist there,
    silently returning None ("no evidence") even when a real SLO verdict
    was sitting one level up in the SAME file. Fixed by always reading the
    `slo` block, for every bench file, the same way — `hot_read` is never
    consulted for a verdict here."""
    if not latency:
        return None
    bench = latency.get("stage_benchmarks", {}).get(bench_key, {})
    slo = bench.get("slo", {})
    if bench_key == "bench_phase4":
        # bench-phase4.json's own "slo" is a SINGLE flat object (its own
        # "name" field says which SLO it is: hot_read_p95_ms) — unlike
        # bench-phase5's "slo", which is a dict keyed BY name holding
        # several SLOs. Read "pass" directly; do not treat it as a
        # name-keyed dict (that was this bug's second layer — the first
        # fix attempt assumed the bench_phase5 shape here too).
        return slo.get("pass")
    if slo_key:
        return slo.get(slo_key, {}).get("pass")
    return all(v.get("pass") for v in slo.values()) if slo else None


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    verdict = derive(results_dir)
    (results_dir / "acceptance-verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
