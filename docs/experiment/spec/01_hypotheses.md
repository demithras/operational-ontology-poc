# 01 — Hypothesis Ledger

Every hypothesis must end the experiment as **SUPPORTED**, **REJECTED**, or **INCONCLUSIVE**. Thresholds may be changed before implementation begins, but not after results are observed without creating a new experiment version.

## H1 — Decision-as-data completeness

**Claim:** Modeling decisions explicitly produces a complete, queryable explanation chain rather than scattering context across logs.

**Required fields/links for every governed decision:**

- immutable `decision_id`
- decision type
- actor principal
- actor delegation context if an agent acts for a human
- decision timestamp
- evidence snapshot identifier
- ontology contract version
- SHACL shape-set version
- authorization model version
- policy bundle version
- action type + action version
- proposed parameters
- authorization result
- policy result
- conformance result
- approval information if required
- execution identifier
- observed outcome identifier
- final status/reason

**Metric:** completeness ratio across all successfully governed decisions.

**Pass:** 100% of required fields/links are present and resolvable.

**Reject:** any successful production-like action lacks required decision provenance.

## H2 — Gates prevent invalid effects

**Claim:** Authorization, business policy, and semantic/transition conformance form enforceable trust boundaries.

**Null hypothesis:** an invalid request can leak through or the system relies on downstream compensation.

**Metric:** number of external side effects caused by denied requests.

**Pass:** `0` side effects across the full negative and adversarial suite.

**Important:** authorization, policy, and SHACL are measured separately; a passing aggregate is insufficient if one boundary is bypassable.

## H3 — Closed-loop truth beats command success

**Claim:** The system can distinguish "command accepted" from "effect observed."

**Metric:** outcome classification under injected cases:
- external API returns 200 but does not mutate state;
- write commits late;
- write partially succeeds;
- CDC is delayed;
- CDC is duplicated;
- CDC is temporarily unavailable.

**Pass:** no case is marked `OBSERVED_SUCCESS` until independently observed state satisfies the expected outcome predicate.

**Reject:** any command-level success is incorrectly treated as world-level success.

## H4 — Durable actions survive faults without duplicate business effects

**Claim:** a durable workflow + idempotency contract can recover across process/network failures.

**Metrics:**
- business effect multiplicity;
- terminal execution status correctness;
- reconciliation correctness.

**Pass:**
- one logical action creates at most one intended business effect;
- all injected recoverable faults converge to a valid terminal or explicitly unresolved state;
- unresolved ambiguity is surfaced, never silently converted to success.

## H5 — Concurrency preserves invariants

**Claim:** competing actions cannot violate domain invariants.

**Primary invariant:** inventory quantity never becomes negative.

**Other invariants:**
- one inventory unit cannot be allocated twice;
- closed/cancelled work orders cannot be rescheduled;
- action version is immutable once referenced by a decision;
- a decision cannot silently switch evidence snapshots.

**Pass:** zero invariant violations under generated concurrent schedules.

## H6 — Hot-path projection provides operational latency without destroying semantic traceability

**Claim:** materialized operational state can meet live decision latency while remaining traceable to semantic/source versions.

**Reference SLO for local POC:**
- hot read p95 `< 200 ms`
- gate evaluation p95 `< 300 ms`
- decision proposal path p95 `< 500 ms` excluding human approval and external write duration

These are experimental SLOs, not universal industry requirements.

**Pass:** SLOs hold under the defined local load while every projection row retains source/event and ontology-version traceability.

**Counter-test:** measure equivalent semantic query directly against the RDF core to quantify why the projection exists.

## H7 — Historical replay remains valid across evolution

**Claim:** a decision can be reconstructed using the versions and evidence that existed at decision time.

**Experiment:** create decisions under contract versions V1/V2, migrate to V3, then replay V1 decisions.

**Pass:** replay reconstructs:
- old evidence snapshot;
- old ontology/schema contract;
- old shape set;
- old authorization model;
- old policy bundle;
- old action definition;
- old decision result;
- actual observed outcome.

**Reject:** replay evaluates old decisions using current rules without explicit opt-in, or old semantics become uninterpretable.

## H8 — Ontology evolution is controlled rather than accidental

**Claim:** ontology is treated as a software contract with compatibility tests and migrations.

**Metrics:**
- migration test success;
- replay success after migration;
- number of silent semantic breaks.

**Pass:** zero silent breaks in seeded historical corpus. Breaking changes fail CI unless accompanied by migration and replay fixtures.

## H9 — Agent capability is bounded by the same hard controls as human/API callers

**Claim:** adding an LLM agent does not weaken authorization or policy enforcement.

**Experiments:**
- prompt injection asks for forbidden action;
- tool-call parameter tampering;
- agent tries an undisclosed/unauthorized tool;
- agent attempts stale-decision execution;
- agent tries to act with broader human credentials.

**Pass:** zero forbidden external effects. Agent identity/delegation is recorded independently of the human identity.

## H10 — Deterministic architecture works without AI

**Claim:** operational ontology value is architectural, not dependent on language-model reasoning.

**Pass:** the canonical incident and all core acceptance tests pass with a deterministic rule-based planner or explicitly supplied decision request.

**Reject:** any critical safety/correctness property requires an LLM.

## H11 — The operational ontology produces measurable benefit over a simpler baseline

**Baseline:** direct SQL/API application using the same fake ERP/MES/WMS and equivalent business rules, but without RDF decision/provenance model, versioned semantic contract, or ontology replay.

**Compare:**
- correct decisions;
- invalid-action rate;
- unsafe-effect rate;
- time to answer "why?";
- historical replay success;
- mean time to diagnose divergence;
- effort to add a new source identifier mapping;
- effort to add a new action;
- change impact when a policy/schema evolves;
- hot-path latency;
- infrastructure and code complexity.

**Success condition:** ontology variant must show a material improvement in at least one declared target dimension (auditability/replayability/change safety/semantic integration) without unacceptable regressions in correctness or latency.

This hypothesis can be **INCONCLUSIVE** if the POC is too small to measure engineering effort credibly.

## H12 — Independent reality checks detect model/world divergence

**Claim:** the system notices when its expected effect differs from observed reality.

**Pass:** injected divergence always creates a reconciliation failure/alert with:
- expected effect;
- observed state;
- relevant action/decision;
- source evidence;
- retry/compensation status.

**Reject:** ontology silently overwrites itself to agree with its prediction or loses the discrepancy.

## H13 — Provenance is queryable, not merely logged

**Claim:** audit questions can be answered by traversable structured relations.

Required queries:

1. Why was decision D made?
2. Which evidence was used?
3. Which evidence was available but excluded?
4. Which policy and authorization model versions were evaluated?
5. Who/what actor proposed, approved, and executed it?
6. Which external objects changed?
7. What outcome was actually observed?
8. Which later decisions depended on that outcome?

**Pass:** all are answerable by stable query/API without log scraping.

## H14 — Semantic openness and operational closure can coexist

RDF/OWL inference is open-world; operations require explicit closure on certain facts.

**Claim:** the system can clearly identify which operational predicates are closed/required at decision time without pretending the entire graph is closed-world.

**Pass:** every action type declares its required evidence and closure assumptions, and missing required evidence causes `INSUFFICIENT_EVIDENCE`, not a guessed false/true result.

## Hypothesis result record

Each hypothesis result must be emitted as:

```yaml
hypothesis: H3
status: SUPPORTED | REJECTED | INCONCLUSIVE
experiment_version: exp-1
git_commit: ...
environment: ...
evidence:
  - test_report: ...
  - traces: ...
  - metrics: ...
notes: ...
```
