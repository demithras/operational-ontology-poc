# 02 — Scope and Non-Goals

## POC boundary

The POC implements one bounded operational loop in a synthetic manufacturing environment.

It is intentionally small enough that every state transition can be understood, modeled, and tested exhaustively or generatively.

## In scope

### Source systems

Three fake legacy systems, logically independent:

**ERP**
- suppliers
- parts
- purchase orders
- purchase-order lines

**MES**
- work orders
- production lines
- BOM requirements
- work-order status

**WMS**
- warehouses
- inventory lots
- on-hand/reserved quantities
- inventory transfers

The systems may share one PostgreSQL server for local resource efficiency, but must use separate databases/schemas, APIs, credentials, and ownership boundaries so the ontology layer cannot cheat with cross-database SQL.

### Semantic identity alignment

The same real-world `Part` must be represented under different local identifiers in ERP/MES/WMS and resolved into one ontology object.

```text
ERP: PART-00192
MES: COMP-A17
WMS: SKU-88429
            |
            v
Ontology: part:PX-17
```

The mapping itself must have provenance.

### Decisions

At minimum:
- shortage mitigation decision;
- transfer approval decision;
- reschedule decision.

### Actions

Initial executable action types:
1. `transfer_inventory`
2. `expedite_purchase_order`
3. `reschedule_work_order`

### Governance

- actor identity;
- OpenFGA authorization;
- OPA business-policy evaluation;
- SHACL structural/transition checks;
- explicit approval for selected high-impact actions;
- immutable decision/action version references.

### Feedback

Every external effect must be observed through the source-system change path before being considered an observed outcome.

### Replay

At least two intentionally incompatible contract generations must be created during the experiment.

### AI

Optional only after deterministic acceptance.

The agent may:
- inspect allowed ontology/hot-view context;
- propose a decision;
- call permitted action tools.

The agent may not:
- bypass action runtime;
- write source databases directly;
- modify OpenFGA/OPA/SHACL;
- mint its own authorization;
- mark outcomes successful.

## Out of scope

The POC is **not** intended to reproduce:

- full Palantir Foundry;
- AIP platform UX;
- enterprise connector catalog;
- production multi-region HA;
- SOC2/FedRAMP/GDPR certification;
- advanced data classification;
- full OWL reasoning;
- enterprise MDM;
- human organization change;
- real SAP/MES/WMS integrations;
- data lakehouse functionality;
- full ontology editor GUI;
- production-scale billions of triples;
- arbitrary natural-language workflow generation;
- automatic ontology induction from documents;
- vector search/RAG as a core requirement;
- real-money or safety-critical execution.

## Anti-scope-creep rule

A feature is included only if it is necessary to test one of the registered hypotheses.

Before adding a component, record:

```text
Which hypothesis becomes untestable without this component?
```

If the answer is "none", postpone it.

## Two operating modes

### Reference mode

Full local architecture:
- RDF4J
- PostgreSQL
- OpenFGA
- OPA
- Temporal
- Kafka
- Debezium
- OpenTelemetry

This is the primary experiment.

### Lite development mode

Allowed for fast inner-loop development:
- RDF4J or rdflib/pySHACL
- PostgreSQL
- in-process fake event bus
- synchronous executor

Lite mode must never be used for final fault-tolerance, CDC, ordering, replay, or latency claims.

## Data volume target

Seed enough data to prevent trivial hard-coding:

- 20 suppliers
- 500 parts
- 2,000 purchase orders
- 4 warehouses
- 10,000 inventory lots
- 200 work orders
- 8 production lines
- 5,000 historical decisions/outcomes for replay/performance tests

The exact dataset can be synthetic and deterministic by seed.

## Local hardware target

The experiment should be runnable on a modern developer workstation with Docker.

The acceptance report must record:
- CPU model/core count;
- RAM;
- OS;
- Docker version;
- container resource limits.

Performance numbers without environment metadata are invalid.
