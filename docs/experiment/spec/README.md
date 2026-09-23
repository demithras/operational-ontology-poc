# Open Operational Ontology — POC Specification Pack

**Status:** experiment specification  
**Version:** 0.1  
**Date:** 2026-09-23  
**Purpose:** define a falsifiable local open-source proof-of-concept (POC) that attacks the thesis presented in *A $250B Lesson: Your Ontology is Missing One Thing* rather than merely illustrating it.

## Core question

Can a small, fully local, open-source operational ontology:

1. drive a concrete operational decision fast enough for a live workflow;
2. reject invalid or unauthorized transitions before external effects occur;
3. execute approved actions reliably against external systems;
4. observe the real outcome instead of trusting its own command path;
5. preserve enough versioned evidence, policy, authority, and provenance to reconstruct and defend the decision months later;
6. outperform or meaningfully de-risk a simpler non-ontology baseline enough to justify the added complexity?

The POC is successful only if these claims survive predefined failure tests. A visually convincing graph, chatbot, dashboard, or happy-path demo is explicitly insufficient.

## Experimental stance

This project is **deterministic-first, AI-second**.

The architecture must first pass all semantic, authorization, policy, transition, execution, reconciliation, replay, and failure-recovery tests without an LLM. Only after that may an AI agent be attached to the same governed action surface.

This prevents model quality from hiding architectural defects.

The project also contains a **baseline implementation** using ordinary SQL + service APIs without an operational ontology. The ontology implementation must be compared with this baseline on decision correctness, unsafe-effect rate, replayability, latency, implementation cost, and change cost.

## POC domain

A synthetic manufacturing and supply-chain loop:

- Supplier
- Part
- PurchaseOrder
- InventoryLot
- Warehouse
- WorkOrder
- ProductionLine
- Shipment

Primary incident:

> A supplier delay threatens a work order. The system must identify the shortage, evaluate alternatives, create a decision record, authorize and validate an inventory transfer, execute it through the fake WMS, observe the actual state change via CDC, and record the outcome.

Initial actions:

- `transfer_inventory`
- `expedite_purchase_order`
- `reschedule_work_order`

## Proposed reference stack

- RDF/semantic core: **Eclipse RDF4J**
- Semantic constraints: **SHACL**
- Provenance vocabulary: **W3C PROV-O**
- Operational/hot projections: **PostgreSQL**
- Relationship authorization: **OpenFGA**
- Contextual business policy: **Open Policy Agent (OPA/Rego)**
- Durable action execution: **Temporal**
- Change Data Capture: **Debezium**
- Event transport/log: **Apache Kafka**
- Test framework: **pytest + Hypothesis stateful testing**
- Observability: **OpenTelemetry**
- Optional agent surface after deterministic acceptance: **MCP**
- Local runtime: **Docker Compose**

These are reference choices, not dogma. Replacements are allowed only if they preserve the experimental properties and are recorded as architecture decisions.

## Package contents

| Document | Purpose |
|---|---|
| `00_thesis.md` | precise thesis under test and what would falsify it |
| `01_hypotheses.md` | hypothesis ledger with metrics, null hypotheses, thresholds |
| `02_scope_and_non_goals.md` | POC boundary and anti-scope-creep rules |
| `03_domain_scenario.md` | synthetic factory world and canonical incident |
| `04_architecture.md` | system architecture, trust boundaries, data flows |
| `05_ontology_and_contracts.md` | RDF domain model, Decision, Evidence, Action, Outcome |
| `06_decision_and_action_runtime.md` | lifecycle and executable action semantics |
| `07_versioning_and_replay.md` | immutable evidence, versioned contracts, historical replay |
| `08_test_strategy.md` | layers of tests and model-based/stateful approach |
| `09_failure_and_adversarial_matrix.md` | crashes, duplicates, races, stale data, attacks |
| `10_ab_experiment.md` | fair ontology-vs-baseline comparison |
| `11_acceptance_criteria.md` | hard pass/fail gates |
| `12_implementation_plan.md` | staged build order and deliverables |
| `13_repository_contract.md` | target repository layout, commands, CI contract |
| `14_risks_and_open_questions.md` | architecture risks and decisions to revisit |
| `SOURCES.md` | primary sources and rationale |

## The two headline acceptance questions

At the end, the test report must answer:

```text
Can it decide now?              PASS / FAIL
Can we prove why later?         PASS / FAIL
```

These are not subjective labels. Their exact requirements are defined in `11_acceptance_criteria.md`.

## Definition of done

The POC is done when a clean machine can:

```bash
git clone <repo>
cd <repo>
docker compose up -d
make seed
make test
make experiment
make replay DECISION_ID=<id>
```

and produce:

- a fully local running stack;
- a machine-readable test report;
- latency and correctness measurements;
- a reproducible A/B experiment;
- at least one deliberately injected failure found and shrunk by Hypothesis;
- a six-month-equivalent historical replay using old ontology/policy/action versions;
- an explicit conclusion for every hypothesis: supported, rejected, or inconclusive.

No hypothesis may be silently dropped.
