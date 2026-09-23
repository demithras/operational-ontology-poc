# 05 — Ontology and Contract Model

## Namespaces

Illustrative only:

```turtle
@prefix oo:   <https://example.local/oo/> .
@prefix fac:  <https://example.local/factory/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
```

## Provenance foundation

Use W3C PROV-O rather than inventing a proprietary provenance vocabulary.

Recommended specialization:

```text
oo:EvidenceSnapshot   subclass/prov:Entity
oo:DecisionActivity   subclass/prov:Activity
oo:ActionExecution    subclass/prov:Activity
oo:Outcome            subclass/prov:Entity
oo:HumanActor         subclass/prov:Agent
oo:SoftwareAgent      subclass/prov:SoftwareAgent
```

Domain-specific relations may be added but should preserve a mapping to PROV where sensible.

## Decision object

A governed decision is a first-class immutable historical object once approved/executed.

Conceptual shape:

```text
oo:DecisionShape
  targetClass oo:Decision

required:
  oo:decisionId exactly 1
  oo:decisionType exactly 1
  oo:actor exactly 1
  oo:evidenceSnapshot exactly 1
  oo:ontologyVersion exactly 1
  oo:shapeSetVersion exactly 1
  oo:authorizationModelVersion exactly 1
  oo:policyBundleVersion exactly 1
  oo:actionType exactly 1
  oo:actionVersion exactly 1
  oo:createdAt exactly 1
  oo:status exactly 1
```

After `APPROVED`, the following are immutable:

- actor/delegation chain;
- evidence snapshot;
- contract versions;
- action type/version;
- proposed parameters.

A new decision must be created to use new evidence or rules.

## Decision lifecycle

```text
DRAFT
  |
  v
PROPOSED
  |
  +--> INSUFFICIENT_EVIDENCE
  +--> DENIED_AUTHORIZATION
  +--> DENIED_POLICY
  +--> INVALID_CONFORMANCE
  +--> REQUIRES_APPROVAL
  |
  v
APPROVED
  |
  v
EXECUTING
  |
  +--> EXECUTION_FAILED
  +--> OUTCOME_UNKNOWN
  |
  v
AWAITING_OBSERVATION
  |
  +--> DIVERGED
  |
  v
OBSERVED_SUCCESS
```

No state named simply `SUCCESS` is allowed for governed actions. Success must communicate whether it is command success or observed-world success.

## Evidence

Evidence must distinguish:

- observed source facts;
- inferred facts;
- derived projection values;
- human assertions;
- agent assertions.

Each evidence item needs:
- origin;
- observed/generated time;
- source position/version;
- derivation rule/version if derived;
- confidence only where meaningful;
- integrity hash.

## Policy references

A decision does not merely record `"policy": "inventory-policy"`.

It records a content-addressed or immutable version:

```text
inventory-policy@sha256:...
```

Same for:
- SHACL shape set;
- OpenFGA model;
- ontology schema;
- action contract;
- projection definition.

Git commit may be used as a convenient aggregate version, but each deployed artifact should still be individually identifiable.

## ActionType contract

Reference YAML:

```yaml
name: transfer_inventory
version: 3

parameters:
  source_warehouse:
    type: Warehouse
  destination_warehouse:
    type: Warehouse
  part:
    type: Part
  quantity:
    type: integer
    min: 1

reads:
  - InventoryLot
  - Warehouse
  - WorkOrder

authorization:
  relation: can_transfer_inventory
  object_binding: source_warehouse

policy:
  package: factory.inventory.transfer

evidence_requirements:
  - current_source_inventory
  - current_destination_compatibility
  - linked_work_order_risk
  - safety_stock

preconditions:
  - source != destination
  - source_available >= quantity

expected_effects:
  - source.available decreases by quantity
  - destination.available increases by quantity

external_operation:
  system: WMS
  operation: create_transfer

idempotency:
  key: action_execution_id

observation:
  source: WMS_CDC
  timeout: PT30S

compensation:
  mode: explicit
  operation: reverse_transfer

audit:
  decision_required: true
  approval_if_policy_requires: true
```

## Difference between constraints, policy, and authorization

### SHACL / conformance

Use for statements like:
- a Decision must have exactly one actor;
- quantity must be positive;
- Approved decision must reference an evidence snapshot;
- transfer source and destination must differ;
- certain RDF transition representations are structurally invalid.

### OpenFGA / authority

Use for:
- this user owns/manages this warehouse;
- this agent has a task-bound grant;
- this planner may execute transfer actions for this region.

### OPA / contextual policy

Use for:
- transfer above 100 units requires supervisor approval;
- safety stock cannot be breached;
- critical parts cannot leave quarantine;
- after-hours actions require a specific obligation.

Overlap may exist, but each rule has one canonical owner to avoid inconsistent duplicated policy.

## Closed-world islands

RDF is generally open-world. Operational decisions cannot infer `false` merely because a fact is absent.

Each ActionType must therefore declare required evidence/closure.

Example:

```yaml
closure:
  required:
    - source_available
    - quality_status
    - safety_stock
  if_missing: insufficient_evidence
```

Absence becomes a typed operational state, not an inference shortcut.

## Source-of-truth hierarchy

For every property, document authority.

Example:

```yaml
Part.description:
  authoritative_source: ERP

InventoryLot.available:
  authoritative_source: WMS

WorkOrder.status:
  authoritative_source: MES
```

The ontology must not casually overwrite authoritative observed facts with model predictions or proposed state.
