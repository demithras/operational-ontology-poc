# Final Experiment Report — exp-003

Generated: 2026-09-24T22:26:47Z
Git commit: `b828fc7a7d13c7899b7dce4b50519e461b723464`

## Headline

```yaml
can_decide_now: PASS
can_prove_why_later: PASS

ontology_thesis:
  H1: SUPPORTED
  H2: SUPPORTED
  H3: SUPPORTED
  H4: SUPPORTED
  H5: SUPPORTED
  H6: SUPPORTED
  H7: SUPPORTED
  H8: SUPPORTED
  H9: SUPPORTED
  H10: SUPPORTED
  H11: REJECTED
  H12: SUPPORTED
  H13: SUPPORTED
  H14: SUPPORTED

critical_failures:
  - "H11 REJECTED: REJECTED: no dimension measured this run shows an ontology-specific advantage once tested like-for-like. Correctness and forensic completeness were at PARITY; replay-across-evolution outcome was at PA"

tradeoffs:
  benefits:
    - "(none measured this run)"
  costs:
    - "No correctness advantage measured: both variants reached IDENTICAL governed decisions across the full generated incident corpus (W7) \u2014 see ab-results.json."
    - "Ontology ingestion lag measurably higher than the baseline's \u2014 see ab-results.json#ingestion_lag_benchmark: {\"trials\": 5, \"mean_lag_ms\": {\"ontology\": 2655.7455085916445, \"baseline\": 624.9220835743472}, \"max_lag_ms\": {\"ontology\": 3072.390625020489, \"baseline\": 1024.121084017679}, \"all_trials_converged\": {\"ontology\": true, \"baseline\": true}, \"note\": \"wall-clock from the WMS write call returning to the varia"
    - "Complexity tax: 23 total containers, 6 ontology-only extra containers + a second store technology (RDF4J) \u2014 see ab-results.json#complexity_tax."
    - "Baseline required ZERO baseline-specific code changes for either contract evolution step (shared deployed_version.json); the ontology's own migrations are real, measured multi-file diffs \u2014 see evolution-comparison.json#migration_effort."
  unknowns:
    - "H11's engineering-cost comparison is drawn from ONE clean baseline-build session vs. many iterative ontology-build phases \u2014 not a time-boxed apples-to-apples methodology (disclosed in Phase 8's own notes); treat magnitude, not precision, as the finding."
    - "No declared target dimension showed a measurable ontology-specific advantage this run \u2014 see H11's notes in hypothesis-results.json for the full dimension-by-dimension breakdown."
```

**Exit code: 0** (0=all mandatory criteria passed, 10=safety, 11=correctness/invariant, 12=replay, 13=performance SLO, 14=experiment/baseline invalid, 15=infra/harness failure — experiments/exp-000/manifest.yaml#exit_codes).

## Headline A — can it decide now? Item-by-item

| # | Item | Result |
|---|---|---|
| 1_canonical_incident | | PASS |
| 2_hot_read_p95 | | PASS |
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

Evidence: fault-results.json#F01, test-results.json#test_shacl_fixtures.py, completeness_sql: {'total': 9117, 'missing_count': 0, 'required_fields': ['decision_id', 'actor_id', 'action_type', 'action_version', 'evidence_snapshot_id', 'ontology_version', 'shape_set_version', 'authorization_model_version', 'policy_bundle_version', 'status']}

F01=PASS, SHACL fixtures clean=True (bad=[]), completeness sweep over 9117 ontology decisions found 0 missing a required linked field.

### H2 — SUPPORTED

Evidence: fault-results.json#F01,F02,F03,F04,F05,F06,F07,F08,F09,F22,F23,F24,F26,F30,F31,F32,F33,F34, test-results.json#tests/agent/*

gate-relevant faults (18 ids) clean=True (FAIL=none, missing=none), agent adversarial suite clean=True (bad=[]). F27 (projection consistency, a data-quality check per spec 11) is deliberately NOT in this set.

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

gate/proposal SLOs pass=True (gate_p95=19.792ms, proposal_p95=56.212ms, thresholds 300ms/500ms), hot_read pass=True (measured_warm_p95=0.239ms, threshold 200ms), host contended at measurement=False.

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

### H11 — REJECTED

Evidence: ab-results.json#W7_generated_incident_corpus,W5_forensic_query,W6_novel_cross_system_relation,ingestion_lag_benchmark,complexity_tax, mutation-results.json#SHACL_CARDINALITY, evolution-comparison.json#migration_effort,replay_sweep, baseline-structural-mutation-probe.json

REJECTED: no dimension measured this run shows an ontology-specific advantage once tested like-for-like. Correctness and forensic completeness were at PARITY; replay-across-evolution outcome was at PARITY (both variants' own real V1/V2-era history replayed cleanly this run); the baseline was AHEAD on change effort, latency, and complexity; and the one dimension that looked like an ontology advantage in an earlier, non-like-for-like check (SHACL structural validation) turned out to be PARITY once the baseline's own equivalent guard was actually mutated and tested live — the baseline's Postgres NOT NULL constraint rejected the same corrupting write at write time, and its replay mechanism independently caught it after the constraint was removed. Per spec 10's own explicitly sanctioned outcome: 'operational ontology is not necessary for this bounded domain.' Dimension-by-dimension: {"correctness": "PARITY \u2014 500/500 W7 decisions matched between variants and vs. the reference-model oracle (ab-results.json#W7_generated_incident_corpus); no ontology advantage.", "forensic": "PARITY \u2014 both variants answered all forensic sub-questions in the same number of calls (ontology=3, baseline=3); W6's novel cross-system query needed comparable new code either side (40 SPARQL vs 32 SQL logical lines, 1 new file each) \u2014 no ontology advantage.", "replay_across_evolution": "PARITY on outcome \u2014 ontology replay sweep exit_code=0 (0=all PASS/PASS_FAIL_CLOSED_VERIFIED), baseline 100.0% PASS-like (220 decisions) \u2014 both variants replayed their OWN real V1/V2-era history cleanly this run (evolution-comparison.json).", "change_effort": "baseline ADVANTAGE \u2014 ZERO baseline-specific files touched for either contract evolution step (git status over services/baseline empty before/after `make deploy-v2`/`deploy-v3`); the ontology's own V1->V2/V2->V3 migrations are real, measured multi-file diffs (evolution-comparison.json#migration_effort)", "latency": "baseline ADVANTAGE \u2014 ingestion lag ontology=2655.7455085916445ms vs baseline=624.9220835743472ms (ab-results.json#ingestion_lag_benchmark).", "complexity": "baseline ADVANTAGE \u2014 23 total containers, 6 ontology-only extra containers + a second store technology (RDF4J) vs 3 baseline-only (ab-results.json#complexity_tax).", "structural_validation_like_for_like": "PARITY \u2014 SHACL_CARDINALITY mutation killed=True; live like-for-like probe against the baseline's own equivalent guard (decisions.evidence_snapshot NOT NULL, the closest real analogue) found baseline_caught_it=True. Baseline's write-time guard (Postgres NOT NULL on `decisions.evidence_snapshot`) DID reject the corrupting write before the mutation was applied \u2014 structurally the same role SHACL_CARDINALITY's target field plays for the ontology variant (reject a write missing required evidence), coarser-grained (whole column, not one nested field). After the mutation removed that guard, the write succeeded, and the baseline's OWN replay mechanism DID independently catch the corruption via hash mismatch (services/baseline/replay.py's evidence_hash_match check, which treats a missing content_hash as an automatic mismatch). The revert was clean."}

### H12 — SUPPORTED

Evidence: fault-results.json#F16,F17, test-results.json#test_divergence.py, mutation-results.json#RECONCILIATION_QUANTITY

F16/F17={'F16': 'PASS', 'F17': 'PASS'}, divergence suite clean=True, RECONCILIATION_QUANTITY mutation killed target=unknown.

### H13 — SUPPORTED

Evidence: latency.json#h13_forensic_query_latency, test-results.json#test_forensic_queries*

all 9 q1-q9 queries answered with >0 timed samples=True, forensic integration/replay/scaling suites clean=True (bad=[]).

### H14 — SUPPORTED

Evidence: fault-results.json#F02, contracts/actions evidence_requirements+closure.required per file: {'contracts/actions/v1/expedite_purchase_order.yaml': True, 'contracts/actions/v1/reschedule_work_order.yaml': True, 'contracts/actions/v1/transfer_inventory.yaml': True, 'contracts/actions/v2/expedite_purchase_order.yaml': True, 'contracts/actions/v2/reschedule_work_order.yaml': True, 'contracts/actions/v2/transfer_inventory.yaml': True, 'contracts/actions/v3/expedite_purchase_order.yaml': True, 'contracts/actions/v3/reschedule_work_order.yaml': True, 'contracts/actions/v3/transfer_inventory.yaml': True}

F02 (missing evidence -> INSUFFICIENT_EVIDENCE)=PASS; every published action type/version declares both `evidence_requirements` and `closure.required`=True (9/9 files).

## Test suite summary

total=310, passed=310, failed=0, errors=0, skipped=0, elapsed_s=656.3

## Fault matrix summary

{'FAIL': 0, 'NOT_TESTED': 0, 'PASS': 40, 'total': 40}

