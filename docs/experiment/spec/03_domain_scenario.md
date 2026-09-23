# 03 — Synthetic Factory Domain and Canonical Scenario

## Why manufacturing

The domain naturally contains fragmented source systems, identity mismatches, temporal state, hard invariants, permissions, policies, external side effects, business alternatives, and measurable outcomes. It is also safely synthetic.

## Canonical object types

- **Supplier:** supplier_id, name, status, lead_time_days, risk_class
- **Part:** canonical_part_id, description, unit, criticality
- **PurchaseOrder:** po_id, supplier, status, promised_at, expected_at, lines
- **WorkOrder:** work_order_id, production_line, status, planned_start, planned_finish, priority, requirements
- **InventoryLot:** lot_id, part, warehouse, on_hand, reserved, available, quality_status
- **Warehouse:** warehouse_id, capacity_class, region
- **ProductionLine:** line_id, status, capabilities
- **Decision:** see `05_ontology_and_contracts.md`
- **ActionExecution:** see `06_decision_and_action_runtime.md`
- **Outcome:** observed result of an attempted action

## Canonical incident

Initial state:

```text
WorkOrder WO-42
  priority = HIGH
  planned_start = T+18h
  requires 80 x Part PX-17

Warehouse WH-A
  PX-17 available = 20

Warehouse WH-B
  PX-17 available = 140

PurchaseOrder PO-991
  PX-17 quantity = 100
  promised arrival = T+8h
```

Event:

```text
Supplier S-7 updates PO-991:
expected_at = T+5d
reason = transport_delay
```

Derived operational fact:

```text
WO-42 shortage = 60
WO-42 at_risk = true
```

Candidate alternatives:

```text
A. transfer 60+ PX-17 from WH-B to WH-A
B. expedite another PO
C. reschedule WO-42
D. combine actions
```

Policy example:

```text
If transfer quantity <= 100
AND source inventory after transfer >= safety_stock
AND destination is compatible
THEN planner may approve.

Otherwise supervisor approval required.
```

Authorization example:

```text
planner:
  can propose transfer
  can execute <= 100 units in assigned region

junior_planner:
  can propose
  cannot approve high-priority-work-order mitigation

agent:
  can propose
  can execute only with task-bound grant
```

## Expected canonical flow

1. ERP event changes expected arrival.
2. Debezium emits source event.
3. Identity resolver maps source objects to ontology objects.
4. RDF core updates observed state/provenance.
5. Projection builder updates `work_order_risk`.
6. Planner reads hot projection.
7. Planner proposes `transfer_inventory`.
8. System captures immutable evidence snapshot.
9. Decision record is created in `PROPOSED` state.
10. OpenFGA evaluates authority.
11. OPA evaluates contextual policy.
12. SHACL validates the proposed governed state/transition.
13. Decision becomes `APPROVED`.
14. Temporal starts ActionExecution.
15. WMS API receives idempotency key.
16. WMS commits transfer.
17. Debezium emits WMS changes.
18. Reconciliation correlates observed changes to expected effects.
19. Outcome becomes `OBSERVED_SUCCESS`.
20. Work-order-risk projection changes from critical to mitigated.
21. Decision provenance links evidence -> decision -> action -> observed outcome.

## Negative canonical cases

### Missing evidence

Supplier delay exists but inventory snapshot is stale beyond allowed age.

Expected:

```text
decision_status = INSUFFICIENT_EVIDENCE
external_effects = 0
```

### Unauthorized actor

Junior user attempts protected transfer.

Expected:

```text
authorization = DENY
external_effects = 0
```

### Policy violation

Transfer would take WH-B below safety stock.

Expected:

```text
policy = DENY or REQUIRE_APPROVAL
external_effects = 0 until approved
```

### SHACL violation

Decision missing policy-version reference. Expected transaction rejection.

### World divergence

WMS accepts command but mutates 50 units instead of 60.

Expected:

```text
execution_command_status = accepted
outcome = DIVERGED
expected = 60
observed = 50
```

Never `success`.

## State-machine invariants

```text
InventoryLot.available >= 0
InventoryLot.reserved >= 0
InventoryLot.on_hand >= InventoryLot.reserved

WorkOrder.status in:
  PLANNED | RELEASED | RUNNING | DONE | CANCELLED

DONE/CANCELLED -> reschedule forbidden

Decision.evidenceSnapshot immutable after approval
Decision.contractVersions immutable after approval

ActionExecution.idempotencyKey unique per logical action

OBSERVED_SUCCESS requires an observed outcome predicate,
not merely executor return status
```
