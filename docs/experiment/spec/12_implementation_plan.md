# 12 — Implementation Plan

Build in vertical slices. Do not start by deploying every infrastructure component.

## Phase 0 — Experiment lock

Deliver:
- finalized hypothesis ledger;
- thresholds;
- canonical scenario fixtures;
- baseline fairness rules;
- ADR template.

No implementation result should change thresholds retroactively.

## Phase 1 — Pure domain model

Implement:
- `WorldState`;
- deterministic transitions;
- invariants;
- canonical incident;
- Hypothesis state machine.

Deliver:

```text
tests/model/
reference_model/
```

Exit:
- generated sequences run;
- shrinking produces minimal failures when deliberate bug injected.

## Phase 2 — Source systems

Implement fake:
- ERP;
- MES;
- WMS.

Each owns a PostgreSQL database/schema and REST API.

WMS includes idempotency and test fault injection.

Exit:
- integration tests;
- canonical scenario can be executed manually.

## Phase 3 — Semantic core

Implement:
- canonical identities;
- RDF4J;
- domain ontology;
- PROV-O mapping;
- SHACL;
- source-event ingestion.

Exit:
- source state represented semantically;
- invalid governed RDF mutations fail.

## Phase 4 — Hot projection

Implement:
- `work_order_risk`;
- `transfer_candidates`;
- current inventory projection;
- freshness/source-position metadata.

Exit:
- projection rebuild test;
- local latency benchmark.

## Phase 5 — Decision service + gates

Implement:
- decision lifecycle;
- evidence snapshots;
- OpenFGA;
- OPA;
- SHACL gate result capture.

Exit:
- all negative gate tests produce 0 effects.

## Phase 6 — Durable action runtime

Implement:
- Temporal workflow;
- WMS action;
- idempotency;
- CDC observation;
- reconciliation.

Exit:
- crash/timeout/duplicate suite passes.

## Phase 7 — Contract versioning/replay

Implement:
- artifact manifests;
- V1/V2/V3 migrations;
- historical corpus;
- replay command.

Exit:
- historical replay acceptance passes.

## Phase 8 — A/B baseline

Build conventional relational implementation with equivalent:
- business logic;
- authorization/policy;
- Temporal execution;
- CDC feedback;
- relational audit.

Run workloads and metrics.

Exit:
- raw comparative report.

## Phase 9 — Agent/MCP

Only now add:
- MCP tool layer;
- agent principal;
- task-based grants;
- adversarial prompts.

Exit:
- no regression in safety acceptance.

## Phase 10 — Final attack

Run:
- complete stateful suite;
- fault matrix;
- mutation tests;
- load benchmark;
- V1 historical replay under V3 deployed state;
- A/B experiment.

Freeze raw artifacts.

## Suggested milestone tags

```text
poc-v0.1-model
poc-v0.2-sources
poc-v0.3-semantic
poc-v0.4-gates
poc-v0.5-actions
poc-v0.6-replay
poc-v0.7-baseline
poc-v0.8-agent
poc-v1.0-experiment
```

## Implementation priorities

```text
correctness
> safety
> observability
> replayability
> performance
> ergonomics
> AI
```

A pretty UI is not required.

## Suggested language split

Pragmatic default:

- Python: reference model, tests, decision service, projections, fake services;
- Java/RDF4J server: use official RDF4J service/container rather than embedding unless needed;
- Rego: OPA;
- FGA DSL: OpenFGA;
- Turtle: RDF/SHACL;
- YAML: actions/config;
- Docker Compose: local orchestration.

The exact application language can change without altering the experiment.
