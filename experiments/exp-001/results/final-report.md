# Final Experiment Report — exp-001

Generated: 2026-09-24T19:46:32Z
Git commit: `b899fc9329658c2f37177b9080ad56bfcecd05b2`

## Headline

```yaml
can_decide_now: INCONCLUSIVE
can_prove_why_later: PASS

ontology_thesis:
  H1: SUPPORTED
  H2: REJECTED
  H3: SUPPORTED
  H4: SUPPORTED
  H5: SUPPORTED
  H6: SUPPORTED
  H7: SUPPORTED
  H8: SUPPORTED
  H9: SUPPORTED
  H10: SUPPORTED
  H11: SUPPORTED
  H12: SUPPORTED
  H13: SUPPORTED
  H14: REJECTED

critical_failures:
  - "F27 FAIL: projection corrupt -> consistency check detects mismatch \u2014 tests/integration/test_projection_consistency.py::test_tampered_row_fails_consistency_check: failed"
  - "H14 REJECTED: F02 (missing evidence -> INSUFFICIENT_EVIDENCE)=PASS; every published transfer_inventory action version declares its required evidence keys=False."
  - "H2 REJECTED: F01-F40 + kill/network/concurrency aux: 39 PASS, 1 FAIL, 0 NOT_TESTED this run."
  - "Safety zero-tolerance check failed \u2014 see acceptance-verdict.json#safety_fail"

tradeoffs:
  benefits:
    - "Declarative structural/state-transition conformance (SHACL) catches a class of defect the relational baseline structurally cannot (mutation-results.json SHACL_CARDINALITY) \u2014 an audit/change-safety benefit, per spec 10's own listed 'ontology's benefit is audit/governance rather than decision correctness' outcome."
  costs:
    - "No correctness advantage measured: both variants reached IDENTICAL governed decisions across the full generated incident corpus (W7) \u2014 see ab-results.json."
    - "Ontology ingestion lag measurably higher than the baseline's \u2014 see ab-results.json#ingestion_lag_benchmark: {\"trials\": 5, \"mean_lag_ms\": {\"ontology\": 2954.7422416042536, \"baseline\": 725.3631501924247}, \"max_lag_ms\": {\"ontology\": 3063.783833058551, \"baseline\": 1034.8197090206668}, \"all_trials_converged\": {\"ontology\": true, \"baseline\": true}, \"note\": \"wall-clock from the WMS write call returning to the vari"
    - "Complexity tax: 23 total containers, 6 ontology-only extra containers + a second store technology (RDF4J) \u2014 see ab-results.json#complexity_tax."
    - "Baseline required ZERO baseline-specific code changes for either contract evolution step (shared deployed_version.json); the ontology's own migrations are real, measured multi-file diffs \u2014 see evolution-comparison.json#migration_effort."
  unknowns:
    - "H11's engineering-cost comparison is drawn from ONE clean baseline-build session vs. many iterative ontology-build phases \u2014 not a time-boxed apples-to-apples methodology (disclosed in Phase 8's own notes); treat magnitude, not precision, as the finding."
```

**Exit code: 10** (0=all mandatory criteria passed, 10=safety, 11=correctness/invariant, 12=replay, 13=performance SLO, 14=experiment/baseline invalid, 15=infra/harness failure — experiments/exp-000/manifest.yaml#exit_codes).

## Headline A — can it decide now? Item-by-item

| # | Item | Result |
|---|---|---|
| 1_canonical_incident | | PASS |
| 2_hot_read_p95 | | INCONCLUSIVE (no evidence this run) |
| 3_gate_p95 | | PASS |
| 4_proposal_p95 | | PASS |
| 5_unauthorized_zero_effects | | PASS |
| 6_policy_denied_zero_effects | | PASS |
| 7_shacl_invalid_no_commit | | PASS |
| 8_concurrency_invariants | | PASS |
| 9_duplicate_retry_one_effect | | PASS |
| 10_no_premature_observed_success | | PASS |
| 11_component_failure_explicit_state | | PASS |
| 12_deterministic_planner_no_llm | | PASS |

## Headline B — can we prove why later? Item-by-item

| # | Item | Result |
|---|---|---|
| 1_all_successful_link_to_decision | | PASS |
| 2_decision_pins_contract_versions | | PASS |
| 3_evidence_snapshot_immutable_reconstructable | | PASS |
| 4_actor_delegation_reconstructable | | PASS |
| 5_authz_policy_versioned_with_hash | | PASS |
| 6_action_version_params_reconstructable | | PASS |
| 7_observed_outcome_linked_to_evidence | | PASS |
| 8_v1_replays_after_v3 | | PASS |
| 9_historical_replay_uses_historical_rules | | PASS |
| 10_forensic_query_answers_all | | PASS |
| 11_deleted_archive_fails_loudly | | PASS |

## Hypothesis ledger (H1-H14) — full evidence

### H1 — SUPPORTED

Evidence: fault-results.json#F01, test-results.json#test_shacl_fixtures.py, completeness_sql: {'total': 9120, 'missing_count': 0, 'required_fields': ['decision_id', 'actor_id', 'action_type', 'action_version', 'evidence_snapshot_id', 'ontology_version', 'shape_set_version', 'authorization_model_version', 'policy_bundle_version', 'status']}

F01=PASS, SHACL fixtures clean=True (bad=[]), completeness sweep over 9120 ontology decisions found 0 missing a required linked field.

### H2 — REJECTED

Evidence: fault-results.json#summary

F01-F40 + kill/network/concurrency aux: 39 PASS, 1 FAIL, 0 NOT_TESTED this run.

### H3 — SUPPORTED

Evidence: test-results.json#test_divergence.py,test_dependency_outage.py,test_cdc_delay_and_kafka_outage.py,test_wms_faults.py

OUTCOME_UNKNOWN/DIVERGED classification suite clean=True, failing=[].

### H4 — SUPPORTED

Evidence: test-results.json#idempotency/worker-crash suite, mutation-results.json#IDEMPOTENCY_HANDLING, test-results.json#test_live_differential.py

idempotency/durability suite clean=True (bad=[]), stateful clean=True, mutation IDEMPOTENCY_HANDLING killed target=unknown (stateful's own IdempotencyBugHuntMachine independently found+shrunk an injected H4 violation — see Phase 10a section).

### H5 — SUPPORTED

Evidence: test-results.json#test_concurrency_race.py,test_concurrent_stock_receipt.py,test_live_differential.py, test-results.json#tests/model/test_stateful.py,test_bug_detection.py

live concurrency suite clean=True (bad=[]), model-level Hypothesis stateful suite clean=True.

### H6 — SUPPORTED

Evidence: latency.json#stage_benchmarks, latency.json#host_load

gate/proposal SLOs pass=True, hot_read pass=None, host contended at measurement=False.

### H7 — SUPPORTED

Evidence: evolution-comparison.json#replay_sweep, evolution-comparison.json#corpus

ontology full replay sweep exit_code=0 (0=all PASS/PASS_FAIL_CLOSED_VERIFIED), baseline full replay sweep fail_or_partial=0 of 220 (baseline replay parity reported for comparison, not gating H7 — H7's claim is specifically about the ontology's versioned-evidence reconstruction mechanism).

### H8 — SUPPORTED

Evidence: test-results.json#test_compat_check.py, fault-results.json#F28,F29, evolution-comparison.json#replay_sweep

compat_check clean=True, F28/F29={'F28': 'PASS', 'F29': 'PASS'}, replay sweep shows silent breaks=False (any real break surfaces as a LOUD FAIL/PARTIAL status, never silence, per services/decision_service/replay.py).

### H9 — SUPPORTED

Evidence: test-results.json#tests/agent/*

tests/agent (F04, F30-F34 adversarial suite) clean=True, failing=[].

### H10 — SUPPORTED

Evidence: test-results.json#test_canonical_scenario.py, test-results.json#tests/model/*

canonical-incident deterministic-planner test clean=True, full tests/model suite clean=True — no LLM involved in either (H9's verdict, not scripts/agent_llm_probe.py, governs H9; H10 rests on these).

### H11 — SUPPORTED

Evidence: ab-results.json#W7_generated_incident_corpus,hot_read_benchmark,ingestion_lag_benchmark, mutation-results.json#SHACL_CARDINALITY, evolution-comparison.json#migration_effort

SUPPORTED, narrowly: the operational ontology's one measurable, ontology-specific advantage this run is declarative structural/state-transition conformance (SHACL) — a general-purpose validator the baseline has no equivalent of. On every OTHER declared dimension this run measured, the baseline matched or beat the ontology: identical governed decisions (correctness parity, not ontology superiority), lower latency/ingestion lag, and materially less engineering effort to support replay across the SAME real contract evolution both variants went through in this run. Read plainly: for THIS bounded domain, operational-ontology machinery is not necessary for correctness or for replay — its measurable value is audit/change-safety governance, exactly one of spec 10's own listed 'expected useful outcomes'. Dimension-by-dimension: {"correctness": "PARITY (no ontology advantage \u2014 identical decisions both variants)", "performance": "ontology WORSE (higher ingestion lag / burst p95 \u2014 see ab-results ingestion_lag_benchmark/hot_read_benchmark)", "change_safety": "ontology BETTER \u2014 SHACL catches a structural/cardinality violation baseline has no equivalent mechanism for (mutation-results.json SHACL_CARDINALITY killed the target with a green control; Phase 8's own baseline build disclosed 'no SHACL-equivalent structural validator' as an honest gap)", "replay_evolution_effort": "baseline REQUIRES ZERO baseline-specific code to pick up a contract redeploy (shared deployed_version.json); ontology's V1->V2/V2->V3 migrations are real, measured multi-file changes (see evolution-comparison.json#migration_effort)"}

### H12 — SUPPORTED

Evidence: fault-results.json#F16,F17, test-results.json#test_divergence.py, mutation-results.json#RECONCILIATION_QUANTITY

F16/F17={'F16': 'PASS', 'F17': 'PASS'}, divergence suite clean=True, RECONCILIATION_QUANTITY mutation killed target=unknown.

### H13 — SUPPORTED

Evidence: latency.json#h13_forensic_query_latency, test-results.json#test_forensic_queries*

all 9 q1-q9 queries answered with >0 timed samples=True, forensic integration/replay/scaling suites clean=True (bad=[]).

### H14 — REJECTED

Evidence: fault-results.json#F02, contracts/actions declared required_evidence: False

F02 (missing evidence -> INSUFFICIENT_EVIDENCE)=PASS; every published transfer_inventory action version declares its required evidence keys=False.

## Test suite summary

total=248, passed=247, failed=1, errors=0, skipped=0, elapsed_s=658.3

## Fault matrix summary

{'FAIL': 1, 'NOT_TESTED': 0, 'PASS': 39, 'total': 40}

