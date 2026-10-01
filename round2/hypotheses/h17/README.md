# H17 — Function and Action are a hard runtime capability boundary

## Claim

The shared Engine can enforce that Functions compute/read but cannot commit governed business effects, while Actions alone can perform governed side effects through authority, policy, preconditions, execution and outcome reconciliation.

## Strong null/rival

Function/Action is only a documentation distinction; code paths or agents can obtain equivalent write capability through Functions or bypass Action governance.

## Why this exists

Separate capability types let the runtime issue different credentials/execution contexts and make effectful transitions impossible from a Function invocation.

## Primary falsifiers

- Any Function can produce a committed business/project side effect through the standard runtime.
- An Action can bypass a required governance gate.
- Function and Action compile to indistinguishable capabilities such that the runtime cannot enforce different effect boundaries.

## Python Hypothesis role

RuleBasedStateMachine generates read/function/propose/approve/deny/retry/crash/execute/observe sequences and shrinks boundary violations.

## Stop rule

- If Functions need committed effects for required use cases, reject the hard-boundary hypothesis and redesign the meta-model explicitly rather than silently granting writes.
