# 11 — Acceptance Criteria

## Headline criterion A — Can it decide now?

`PASS` only if all mandatory conditions pass:

1. Canonical incident produces a correct mitigation decision or an explicit policy/authority/evidence refusal.
2. Hot read p95 < 200 ms under declared local benchmark.
3. Gate path p95 < 300 ms.
4. Proposal path p95 < 500 ms excluding external execution/human wait.
5. Unauthorized attempts cause 0 external effects.
6. Policy-denied attempts cause 0 external effects.
7. SHACL-invalid governed mutations do not commit.
8. Concurrency never violates inventory/domain invariants.
9. Duplicate/retry tests create at most one intended business effect per logical execution.
10. Outcome is not marked observed success before CDC-based reconciliation.
11. Component failure causes explicit unavailable/pending/unknown state, not fabricated certainty.
12. Deterministic planner path passes without an LLM.

Any failure of items 5–10 is a hard fail regardless of aggregate percentage.

## Headline criterion B — Can we prove why later?

`PASS` only if:

1. 100% of governed successful actions link to a Decision.
2. Each Decision contains/pins all required contract versions.
3. Evidence snapshot is immutable and reconstructable.
4. Actor/delegation chain is reconstructable.
5. Authorization and policy results are stored with version/input hash.
6. Action type/version and exact parameters are reconstructable.
7. Observed outcome is linked to source evidence.
8. V1 decisions replay successfully after V3 migration.
9. Historical replay uses historical rules, not current rules.
10. A forensic query can answer:
   - who;
   - what evidence;
   - what policy;
   - what authorization;
   - what action;
   - what actual outcome;
   - what changed next.
11. Deleting/replacing an old contract artifact causes a test failure, proving replay actually depends on preserved versions.

## Safety acceptance

Zero tolerance:
- unauthorized external side effect;
- policy-denied external side effect;
- negative inventory;
- approval applied to mutated decision;
- silent world/model divergence;
- agent bypass of server-side controls.

## Data-quality acceptance

- ambiguous identity never auto-merges silently;
- required missing facts become `INSUFFICIENT_EVIDENCE`;
- stale hot data is detectable;
- projection can be rebuilt;
- duplicate CDC does not duplicate business state.

## Reliability acceptance

Injected:
- worker crash;
- commit-then-timeout;
- delayed CDC;
- duplicate events;
- temporary dependency outage.

All must converge or terminate in an explicit actionable unresolved state.

## Replay acceptance corpus

Minimum:
- 100 V1 decisions;
- 100 V2 decisions;
- 5,000 total historical decision records for query/load tests;
- successful, denied, failed, diverged, and unknown outcomes represented.

## A/B acceptance

The project does **not** require ontology to "win."

The experiment passes scientifically if:
- both variants are implemented fairly enough for declared workloads;
- raw metrics are preserved;
- trade-offs are reported;
- hypothesis conclusions follow evidence.

The *ontology thesis* receives support only where ontology-specific mechanisms show measurable benefit.

## Exit statuses

Recommended:

```text
0   all mandatory acceptance criteria passed
10  safety failure
11  correctness/invariant failure
12  replay failure
13  performance SLO failure
14  experiment/baseline invalid
15  infrastructure/test harness failure
```

## Required final report conclusion

```yaml
can_decide_now: PASS | FAIL
can_prove_why_later: PASS | FAIL

ontology_thesis:
  H1: SUPPORTED | REJECTED | INCONCLUSIVE
  ...
  H14: ...

critical_failures: []
tradeoffs:
  benefits: []
  costs: []
  unknowns: []
```
