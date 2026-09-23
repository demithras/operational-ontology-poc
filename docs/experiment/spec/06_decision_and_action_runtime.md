# 06 — Decision and Action Runtime

## Goal

Convert an operational request into a governed, durable, observable state transition.

## API surface

Minimum endpoints or equivalent internal commands:

```text
POST /decisions/propose
GET  /decisions/{id}
POST /decisions/{id}/approve
POST /decisions/{id}/execute
GET  /executions/{id}
GET  /outcomes/{id}
POST /replay/{decision_id}
```

The API may merge steps internally, but audit states must remain explicit.

## Proposal algorithm

```text
propose(request):
  authenticate actor

  read hot/context data
  resolve canonical identities

  evidence = freeze_required_evidence(request)
  decision = create PROPOSED(evidence, current contract versions)

  authz = openfga.check(actor, requested capability, target)
  persist authz result
  if deny:
      decision -> DENIED_AUTHORIZATION
      return

  policy = opa.evaluate(exact decision input)
  persist policy input hash + result + bundle version
  if deny:
      decision -> DENIED_POLICY
      return
  if require approval:
      decision -> REQUIRES_APPROVAL
      return

  proposed_mutation = build_semantic_transition(decision)
  shacl_result = validate(proposed_mutation)
  persist result
  if invalid:
      decision -> INVALID_CONFORMANCE
      return

  decision -> APPROVED
  return
```

## Execute algorithm

Execution must verify that it is executing the *approved immutable tuple*.

```text
execute(decision_id):
  load APPROVED decision
  verify immutable content hash
  verify not already terminal/executing incompatibly
  create ActionExecution(action_execution_id)

  start Temporal workflow(action_execution_id)

workflow:
  call external API with action_execution_id as idempotency key
  persist command receipt/status
  wait for correlated CDC observation
  evaluate outcome predicate

  if observed expected effect:
      outcome = OBSERVED_SUCCESS

  elif observed contradictory effect:
      outcome = DIVERGED

  elif timeout and external status cannot resolve:
      outcome = OUTCOME_UNKNOWN

  elif known failed with no effect:
      outcome = EXECUTION_FAILED
```

## Exactly-once language

The design must **not** promise magical distributed exactly-once execution.

The business objective is:

> repeated delivery/retry of the same logical ActionExecution must not create duplicate intended business effects.

Achieve through:
- stable idempotency key;
- deduplication at WMS API boundary;
- durable execution history;
- reconciliation;
- compensating action only when semantics permit.

## WMS fake API requirements

`POST /transfers`

Headers/body must include:
- `action_execution_id`;
- source;
- destination;
- part;
- quantity.

WMS persists a unique constraint on `action_execution_id`.

Test mode supports fault injection:

```text
return_500_before_commit
commit_then_timeout
return_200_without_commit
partial_commit
delay_commit
duplicate_response
```

## Outcome predicate

An ActionType defines its observable success predicate.

For `transfer_inventory(q)`:

```text
source.available_after
  == source.available_before - q

AND

destination.available_after
  == destination.available_before + q

AND

a WMS transfer record exists for action_execution_id
```

If another legitimate concurrent event changes stock, the predicate must use correlated transaction/transfer facts rather than naive absolute arithmetic.

## Human approval

Policy may emit:

```json
{
  "decision": "require_approval",
  "obligations": [{
    "type": "approval",
    "relation": "can_approve_large_transfer"
  }]
}
```

Approval itself is a provenance event with:
- approver;
- time;
- decision hash;
- policy version;
- approval scope.

Any mutation to decision input invalidates the approval.

## Reconciliation states

```text
NOT_STARTED
COMMAND_SENT
COMMAND_ACCEPTED
AWAITING_OBSERVATION
CONVERGED
DIVERGED
OUTCOME_UNKNOWN
COMPENSATING
COMPENSATED
FAILED
```

## Separation of proposal and execution

A proposed action may be evaluated without external effects.

This enables:
- human review;
- scenario analysis;
- agent proposals;
- policy explanation;
- A/B decision comparison.

## MCP layer (phase 2 only)

Recommended tools:

```text
get_object
query_work_order_risk
list_transfer_candidates
propose_transfer_inventory
get_decision
execute_approved_decision
explain_decision
```

The agent should never receive generic:
- `run_sql`;
- `write_triple`;
- unrestricted HTTP;
- direct source-system credentials.

Tool discovery itself should be authorization-filtered where feasible.
