# Phase 8 A/B trade-off table (Variant B: operational ontology vs Variant A: relational baseline)

Generated from `experiments/exp-000/results/ab-results.json` (2026-09-24T22:12:55.344405+00:00).
No weighted winner score (spec 10). Per-metric table; conclusions tied to H1-H14 belong in the phase report, not here.

## Correctness

| Metric | Ontology | Baseline | Note |
|---|---|---|---|
| W1 decision matches (variants agree) | True | True | canonical-shape synthetic scenario |
| W1 matches reference_model oracle | True | True |  |
| W4 decision matches / oracle match | True | True | reserved>0 post-evolution representation |
| W6 novel-relation query results match | True | True |  |
| W7 corpus (n=500) — decision match rate between variants | 1.0 | 1.0 | same figure both sides by construction (a pairwise rate) |
| W7 — match rate vs reference_model oracle (n_checked=394) | 1.0 | 1.0 | oracle skips role-authz scenarios — see tests/ab/generator.py |
| Invariant violations / unsafe external effects observed | 0 | 0 | both reuse the SAME authz.py/policy.py gate code (item 1) — safety proof inherited, not independently fault-tested per variant this phase |

## Explainability / audit (W5)

| Metric | Ontology | Baseline | Note |
|---|---|---|---|
| Forensic query complete (7 sub-questions answered) | True | True |  |
| Distinct calls needed | 3 | 3 |  |
| Manual log sources needed | 1 | 1 | both: 1 (the service's own API) — no separate log-scraping needed either side |
| Wall-clock to reconstruct | 11 ms | 7 ms |  |

## Replay / evolution

| Metric | Ontology | Baseline | Note |
|---|---|---|---|
| V1-era historical decision replays under HISTORICAL (not current) rule | True | N/A | baseline was built in Phase 8, AFTER V1->V2 already happened — no V1-era history of its own (disclosed asymmetry, docs/experiment/implementation-notes.md item 1) |
| Fresh decision replays under its OWN pinned version | PASS | PASS |  |
| % of ALL decisions in the store that replay PASS-like | 5,293/5,293 = 100% (0 FAIL, 0 PARTIAL — see fault-matrix-phase8.json / Phase 8 step 0 section) | 5525/5525 = 100.0% | baseline's corpus is entirely Phase-8-session-generated (no multi-month history) |
| Migration failures / silent semantic breaks | 0 (make test-replay, make test-faults — see implementation-notes.md) | 0 (baseline_replay_sweep.py — see above) |  |

## Operational performance

| Metric | Ontology | Baseline | Note |
|---|---|---|---|
| p95 proposal latency (isolated, warm, Phase 5 bench) | 55.24 ms | not separately isolated-benchmarked this phase | see bench-phase5.json |
| p95 proposal latency (W7 corpus, n=500, concurrent-burst conditions) | 55.1 | 59.9 | ms — both well under the 500ms SLO; baseline measurably lower under burst load, see implementation-notes.md for the freshness-retry mechanism that explains most of the gap |
| p95 hot read | 0.7 | 0.8 | ms, n=30 — both sub-2ms, no material difference |
| Ingestion lag (WMS write -> own read path reflects it) | 2655.7 ms mean | 624.9 ms mean | n=5 trials — see docs/experiment/implementation-notes.md item 1 for the two-watermark-vs-one design difference this reflects |
| Reconciliation | separate standing service (H12, independent re-check) | inline in the action-execution workflow | disclosed scope choice, item 1 |

## Engineering cost

| Metric | Ontology | Baseline | Note |
|---|---|---|---|
| Total build effort (this specific artifact) | 9538 logical lines (accumulated Phases 3-7b, many commits) | 2073 logical lines (1 commit: 73d8221189) | NOT apples-to-apples methodology — see engineering_cost.note in ab-results.json |
| W2: effort to add a new source identifier mapping | 1 file(s), 12 lines | 1 file(s), 12 lines | SAME file both sides — services/identity_resolver reused verbatim (item 1's fairness decision); figure is from FIRST application (this run found it already applied) |
| W6: effort to add a novel cross-system relation | 40 lines, 0 migrations | 32 lines, 0 migrations | new query only, both sides — no schema/ontology change needed either way |

## Complexity tax

| Metric | Ontology (extra over shared) | Baseline (extra over shared) | Note |
|---|---|---|---|
| Extra containers | 6 | 3 | of 23 total, 12 shared |
| Extra store technologies | RDF4J (separate triple store + its own docker volume, oo-poc-rdf4j-data) | 0 |  |

## Workload status

| Workload | Status |
|---|---|
| W1_canonical_supplier_delay | OK |
| W2_identifier_mismatch_and_mapping_change | OK |
| W3_policy_evolution | OK |
| W4_schema_evolution | OK |
| W5_forensic_query | OK |
| W6_novel_cross_system_relation | OK |
| W7_generated_incident_corpus | OK |

