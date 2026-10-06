# H29 — Paladin preserves safe continuity and deterministic recovery inside a bounded fault envelope

## Claim

Within a frozen survivability envelope, the Paladin machine preserves all safety invariants under bounded component failure or compromise, continues operations whose required trust/effect dependencies remain available, fails explicitly when they do not, and reconstructs a deterministic safe state after recovery.

## Strong null / rival

The added governance/security layers improve denial safety only by making the system brittle: partial failure either stops unrelated operations, creates ambiguous stale state, or requires manual recovery that can violate the same invariants.

## Mechanism under test

Capabilities, authority versions, action state, provenance and observations are explicit enough to distinguish safe-to-continue work from dependency-blocked work; durable idempotent execution plus deterministic projection/replay reconstructs in-flight state without inventing authority or outcome.

## Primary falsifiers

- Any fault sequence creates a forbidden effect, false success or stale-authority commit.
- An unrelated healthy operation is blocked often enough to violate the frozen safe-progress threshold.
- Recovery produces a canonical state different from replay of the same history.
- A dependency failure is misreported as an ordinary policy denial or success.

## Experiment

Fault/compromise state-machine experiment separating safety, safe progress, explicit unavailability and deterministic recovery.

1. Freeze the survivability envelope and per-operation dependency graph.
2. Generate mixed workloads before, during and after faults/partitions/restarts.
3. Track safety invariants and safe-progress eligibility independently.
4. Crash/restart Engine, authority/policy dependencies, adapters and observation/event paths according to the envelope.
5. Rebuild/recover and compare canonical state and in-flight action status with an independent replay model.
6. Inject fail-open, global-stop, stale-cache and nondeterministic-recovery mutants.

## Independent oracle

Independent dependency graph + pure lifecycle/replay model that marks each operation SAFE_TO_RUN, BLOCKED_BY_DEPENDENCY or UNRESOLVED and predicts canonical post-recovery state.

## Fair baseline

Conventional resilient typed/event workflow implementation with equivalent retries, idempotency, circuit breakers, policy/auth dependencies and recovery objectives.

## Stop rule

- Do not use the phrase "under any conditions" as an experimental claim; if the frozen envelope is insufficient, add a new envelope/version rather than retroactively expanding or shrinking it.
