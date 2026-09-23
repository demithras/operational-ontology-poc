# 08 — Test Strategy

## Philosophy

Test the system as a state machine and a distributed protocol, not as a set of REST endpoints.

A happy-path integration test is necessary and radically insufficient.

## Test pyramid

### Level 0 — Pure reference model

A small deterministic Python model acts as oracle:

```python
WorldState
transition(state, action) -> state | rejection
derive(state) -> derived facts
```

No network, DB, RDF, or LLM.

The oracle encodes only domain rules, not implementation details.

### Level 1 — Contract/unit tests

- SHACL shapes;
- Rego policies;
- OpenFGA models;
- action YAML/schema;
- identity mapping;
- outcome predicates;
- migrations.

### Level 2 — Component tests

Each service with real storage where relevant.

### Level 3 — Integration tests

Real containers, real network, real DBs.

### Level 4 — Stateful/model-based tests

Hypothesis generates sequences of commands/events.

### Level 5 — Fault-injection tests

Kill/restart/timeout/reorder/duplicate.

### Level 6 — Performance tests

Hot path and gate latency.

### Level 7 — A/B experiment

Operational ontology vs direct SQL/API baseline.

### Level 8 — Agent adversarial tests

Only after Levels 0–7 pass.

## Reference-model interface

Possible pure model:

```python
@dataclass(frozen=True)
class WorldState:
    inventory: ...
    work_orders: ...
    purchase_orders: ...
    permissions: ...
    policy_config: ...

def propose_transfer(state, actor, ...): ...
def execute_transfer(state, approved_decision): ...
```

The real implementation is compared against canonical state after normalized event convergence.

## Stateful testing

Hypothesis rules may include:

```text
supplier_delay()
supplier_recovery()
receive_inventory()
reserve_inventory()
release_inventory()
propose_transfer()
approve_transfer()
execute_transfer()
retry_execution()
reschedule_work_order()
cancel_work_order()
change_permission()
change_policy()
restart_service()
delay_cdc()
duplicate_cdc()
```

Invariants evaluated after every convergence point:

```text
inventory >= 0
no forbidden side effects
decision immutability
projection consistency
source/ontology consistency within defined lag
```

Hypothesis shrinking is valuable: the final failure should become the smallest reproducible event sequence.

## Differential testing

Run the same generated domain command sequence against:

1. pure reference model;
2. operational ontology implementation.

Normalize technical details and compare business state.

Where eventual consistency exists:
- wait for declared convergence bound;
- if bound is exceeded, fail with `non_convergence`.

## Metamorphic tests

Examples:

- duplicating an identical CDC event must not change final business state;
- replaying a processed command with same idempotency key must not create a second effect;
- reordering independent events should not change converged state;
- adding irrelevant RDF facts should not change an action decision;
- renaming a source-local identifier while preserving identity mapping should not change canonical result.

## SHACL tests

Positive fixtures:
- valid decision;
- valid transfer.

Negative fixtures:
- missing actor;
- missing evidence;
- missing policy version;
- negative quantity;
- malformed state transition.

For governed writes, invalid fixtures must fail commit or pre-commit transaction.

## OPA tests

At minimum:
- below threshold allowed;
- above threshold requires approval;
- safety stock denial;
- quarantine denial;
- stale evidence denial/obligation;
- unknown required input => non-allow.

Use `opa test --fail-on-empty` in CI.

## OpenFGA tests

At minimum:
- planner allowed within scope;
- planner denied outside scope;
- junior denied protected approval;
- agent denied without task grant;
- agent allowed with exact task grant;
- revoked grant immediately denies future execution.

## Idempotency tests

For each action execution:
- send once;
- send twice sequentially;
- send twice concurrently;
- retry after timeout;
- restart workflow then retry.

Expected one business effect.

## Reconciliation tests

Inject:
- 200/no mutation;
- partial mutation;
- wrong quantity;
- wrong target;
- delayed observation;
- duplicate observation;
- unrelated concurrent mutation.

Expected classifications must be deterministic.

## Performance methodology

Measure separately:

```text
hot projection read
authorization check
policy evaluation
SHACL validation
decision persistence
end-to-end proposal
external action duration
CDC observation lag
reconciliation time
```

Do not hide slow stages in one average.

Report:
- p50;
- p95;
- p99;
- max;
- sample count;
- warm/cold condition;
- machine/container resources.

## Replay tests

Historical corpus:
- minimum 5,000 decisions generated across versions for replay/performance;
- at least 200 have complete action/outcome chains;
- include denied and diverged decisions.

Expected:
- exact contract version recovery;
- exact evidence hash recovery;
- same original gate results.

## Mutation testing (recommended)

Deliberately alter:
- policy comparator (`<=` to `<`);
- SHACL cardinality;
- authorization relation;
- reconciliation quantity;
- idempotency handling.

The test suite should catch each mutation. If it does not, the suite is not strong enough.

## Test report artifact

`experiment-report.json`:

```json
{
  "git_commit": "...",
  "environment": {},
  "hypotheses": {},
  "tests": {},
  "latency": {},
  "faults": {},
  "ab": {},
  "headline": {
    "can_decide_now": "PASS",
    "can_prove_later": "PASS"
  }
}
```
