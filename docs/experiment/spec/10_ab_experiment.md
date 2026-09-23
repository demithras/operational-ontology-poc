# 10 — A/B Experiment: Operational Ontology vs Simpler Baseline

## Why a baseline is mandatory

A POC that only proves "the ontology system can work" does not prove that ontology is the useful causal ingredient.

We need a simpler control implementation.

## Shared environment

Both variants use the same:
- synthetic dataset;
- ERP/MES/WMS;
- source APIs;
- fault injection;
- business incidents;
- actors/permissions;
- policy rules;
- test seeds;
- hardware.

## Variant A — Baseline

Conventional service architecture:

```text
source DBs/APIs
   -> integration service
   -> PostgreSQL application model
   -> business service
   -> source APIs
   -> logs/audit tables
```

No RDF semantic core. No PROV-O decision graph. No semantic contract replay. No SHACL.

Authorization/policy may still be implemented because comparing against an intentionally unsafe strawman would be invalid.

Recommended baseline:
- PostgreSQL domain tables;
- normal schema constraints;
- OpenFGA and OPA retained;
- same Temporal execution;
- same CDC observation path;
- explicit audit table implemented using conventional relational design.

This makes the comparison harder and fairer.

## Variant B — Operational ontology

Adds:
- RDF semantic core;
- canonical identity graph;
- decision/evidence/outcome graph;
- SHACL;
- versioned ontology semantics;
- provenance relations;
- semantic replay/migrations;
- hot projections derived from the semantic core.

## Important consequence

If the baseline also supports excellent decision records, durable actions, and replay with ordinary relational structures, that is a meaningful result.

The experiment is allowed to conclude:

> Operational ontology is not necessary for this bounded domain.

That would be a valid falsification/qualification.

## Workloads

### W1 — canonical supplier delay
Simple known flow.

### W2 — cross-system identifier mismatch
Part IDs differ and one mapping changes.

### W3 — policy evolution
Safety-stock rule changes after historical decisions exist.

### W4 — schema evolution
Inventory representation changes from one `available` field to `on_hand - reserved`.

### W5 — forensic query
Given an outcome six simulated months later:
- explain why action happened;
- identify evidence and actor;
- identify exact old rules;
- reconstruct old decision.

### W6 — novel relation query
Add a new relationship crossing ERP/MES/WMS and measure implementation effort.

### W7 — generated incident corpus
500–1000 incident sequences.

## Metrics

### Correctness
- decision match vs reference model;
- invariant violations;
- unsafe effects.

### Explainability/audit
- forensic-query completion;
- number of manual log sources required;
- time/steps to reconstruct.

### Replay/evolution
- percentage of historical decisions replayed;
- migration failures;
- silent semantic breaks.

### Operational performance
- p95 proposal latency;
- p95 hot read;
- ingestion lag;
- reconciliation lag.

### Engineering cost
Record rather than pretend precision:
- files changed;
- logical lines changed;
- components touched;
- migrations needed;
- tests added;
- wall-clock implementation time if performed by same agent/team and instrumentable.

### Complexity tax
- running containers;
- persistent stores;
- deployment artifacts;
- failure modes;
- average CI duration.

## No weighted "winner" score

Do not collapse everything into one arbitrary score. Produce a trade-off table per metric and a conclusion tied to original hypotheses.

## Fairness rules

1. Same business semantics.
2. Same incident seeds.
3. Same external source behavior.
4. Same authorization/policy where applicable.
5. Same durable execution where applicable.
6. No ontology-specific question should be counted as a baseline failure unless it represents a real required capability.
7. Measure implementation complexity honestly.
8. Do not optimize one variant after seeing the other's final benchmark without rerunning both under a new experiment version.

## Expected useful outcomes

All are acceptable:

- ontology clearly wins on replay/integration semantics;
- relational baseline is sufficient at this scale;
- ontology helps only after a complexity threshold;
- ontology's benefit is audit/governance rather than decision correctness;
- performance tax is too high without projections;
- SHACL adds useful state-transition safety but RDF adds little;
- decision-as-data is the main benefit independent of graph technology.

The experiment exists to discover which statement is true.
