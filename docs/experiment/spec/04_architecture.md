# 04 — Reference Architecture

## Architectural principle

The graph is the semantic core, not the only runtime data structure. Operational correctness requires distinct trust boundaries and distinct representations optimized for different jobs.

## Component diagram

```text
                    ┌──────────────────────────────────────┐
                    │         VERSIONED CONTRACT REPO       │
                    │ RDF/OWL | SHACL | Rego | FGA | YAML  │
                    └──────────────────┬───────────────────┘
                                       │ version IDs
                                       v
  ┌────────────┐   CDC    ┌───────────────────────────────┐
  │ ERP / MES  │─────────►│ Kafka / event log             │
  │ / WMS      │          └──────────────┬────────────────┘
  └─────▲──────┘                         │
        │                                v
        │                  ┌───────────────────────────────┐
        │                  │ Ingestion / identity resolver │
        │                  └──────────────┬────────────────┘
        │                                 v
        │                  ┌───────────────────────────────┐
        │                  │ RDF4J semantic core + SHACL   │
        │                  │ observed state + provenance   │
        │                  └──────────┬─────────┬──────────┘
        │                             │         │
        │                             │         └────► audit/replay store
        │                             v
        │                  ┌──────────────────────┐
        │                  │ projection builder   │
        │                  └──────────┬───────────┘
        │                             v
        │                  ┌──────────────────────┐
        │                  │ PostgreSQL hot state │
        │                  └──────────┬───────────┘
        │                             │
        │                             v
        │                   Decision API / MCP
        │                             │
        │                 ┌───────────┼───────────┐
        │                 v           v           v
        │             OpenFGA        OPA        SHACL
        │              authority    policy    conformance
        │                 └───────────┼───────────┘
        │                             v
        │                         APPROVED
        │                             │
        │                             v
        │                     Temporal workflow
        │                             │
        └──────── external APIs ◄─────┘
```

## Component responsibilities

### Fake source systems

Own their operational state. The ontology is not allowed to mutate their databases directly.

Each source exposes:
- API;
- transactional DB;
- health endpoint;
- fault injection endpoint available only in test mode.

### Debezium

Captures committed row-level source changes. CDC is the primary observation path for the closed loop.

### Kafka

Carries durable source events and allows replay of observation streams. Kafka is not the authoritative business database; it is the durable event transport/log.

### Identity resolver

Maps source-local identifiers to canonical ontology identities.

Every mapping must record:
- mapping rule/version;
- source identifiers;
- confidence/authority;
- creation/change time.

Ambiguous identity is a first-class failure, not silently guessed.

### RDF4J semantic core

Stores canonical objects, relationships, observed source facts, decision objects, evidence snapshots, provenance, policy/action/version references, and outcomes.

SHACL-enabled transactions reject mandatory conformance violations.

### SHACL

Responsible for required fields, datatype/cardinality constraints, selected transition-state constraints, required decision evidence references, and required version references.

SHACL is **not** the sole authorization system and **not** the sole business-policy engine.

### PostgreSQL hot projections

Stores operationally optimized materialized state, e.g.:

```text
work_order_risk
transfer_candidates
current_inventory
action_eligibility_summary
```

Every projection row must include enough traceability to identify source event offsets/versions, projection version, ontology contract version, and computed-at time.

### OpenFGA

Answers relationship/authority questions such as:

```text
Can principal P execute action A on object O?
Can agent G act on behalf of user U for task T?
```

It must be checked at action time, not only when rendering UI/tools.

### OPA

Evaluates contextual business policy, with explicit input document.

Policy result should be structured:

```json
{
  "decision": "allow | deny | require_approval",
  "reasons": [],
  "obligations": []
}
```

### Decision service

Orchestrates decision creation and gates. It must not collapse gate results into one opaque boolean.

### Temporal

Executes durable actions, including idempotency, retries, timeouts, compensation where safe, unresolved/ambiguous terminal states, and correlation with observed outcomes.

### Reconciliation service

Compares expected effects with CDC-observed facts. This is the boundary between "we asked" and "the world changed."

### OpenTelemetry

All requests should propagate:
- `trace_id`
- `decision_id`
- `action_execution_id`
- `actor_id`

Traces are diagnostic evidence, not the canonical decision record.

## Trust-boundary order

Reference order:

```text
request
  -> authenticate
  -> authorize (OpenFGA)
  -> policy decision (OPA)
  -> create/lock evidence snapshot
  -> validate governed mutation/transition (SHACL)
  -> persist approved decision
  -> execute action (Temporal)
  -> observe source change (CDC)
  -> reconcile expected vs observed
  -> finalize outcome
```

Some implementation details may require transactional choreography. The externally visible safety invariant is:

> No protected external effect occurs unless all required pre-execution gates passed against the exact immutable decision/evidence/version tuple being executed.

## Consistency model

Do not pretend the entire distributed system is one ACID transaction.

Explicitly model:
- authoritative source state;
- semantic observed state;
- projection freshness;
- proposed state;
- expected effect;
- observed effect;
- convergence status.

Required statuses:

```text
FRESH
STALE
PENDING_OBSERVATION
CONVERGED
DIVERGED
UNKNOWN
```

## Evidence snapshot

The snapshot is not necessarily a full graph copy. It may be a content-addressed manifest:

```yaml
snapshot_id: es-9211
observed_at: ...
ontology_version: ...
source_positions:
  erp: lsn/offset
  mes: ...
  wms: ...
facts:
  - canonical fact IDs / hashes
projection_rows:
  - row IDs / hashes
content_hash: ...
```

The replay implementation must prove that the decision input can be reconstructed exactly enough to reproduce gate results.

## Security rule

No LLM or UI client receives direct write credentials for ERP/MES/WMS databases. All governed mutations pass through the action runtime.
