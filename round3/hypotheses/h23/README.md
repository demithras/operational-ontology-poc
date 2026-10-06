# H23 — Compromised agents remain effect-contained

## Claim

A Paladin execution boundary can treat any single planner/agent as fully compromised and still prevent every external or canonical effect outside the authority, resource scope, action type and current capability legitimately issued to that agent.

## Strong null / rival

Agent containment is mostly a property of cooperative callers; a malicious caller can exploit tool discovery, parameter substitution, identity confusion, replay or state manipulation to create an effect that the declared authority model did not permit.

## Mechanism under test

Generated capability-aware surfaces minimize exposed operations, while the Engine independently rechecks identity, current authority, policy, preconditions and immutable gated inputs before any effect; returned records are non-authoritative views rather than mutable execution state.

## Primary falsifiers

- Any supported caller path creates an external/canonical effect not present in the independent authority/effect oracle.
- A caller changes identity, gated inputs, target resource or action after authorization and the changed effect commits without a fresh valid decision.
- The only thing preventing a forbidden effect is absence of a tool while the directly reachable Engine path would allow it.

## Experiment

Adversarial state-machine experiment that gives a hostile caller every supported call and parameter available to a principal and compares committed ground-truth effects with an independent capability oracle.

1. Freeze principals, delegations, action schemas, effect ground truth and the public call surface.
2. Generate valid and malicious call sequences including discovery, identity substitution, parameter mutation, replay, retry, crash and stale decisions.
3. Record actual external/canonical effects independently of Engine return values.
4. Cross-check every effect against the oracle authorization set at the moment the effect became eligible.
5. Attack the Engine directly as well as through generated tools so tool hiding is not credited as the only defense.
6. Inject tool-overexposure, mutable-gated-input and identity-confusion mutants; require detection.

## Independent oracle

Pure capability/effect model built from frozen principal, authority, policy and resource fixtures, plus an effect meter that reads external/canonical ground truth rather than candidate logs.

## Fair baseline

Strong conventional typed API/tool surface with least-privilege credentials and independent service-side authorization, used contextually here and as the full comparator in H30.

## Stop rule

- A single real forbidden effect rejects the current containment design; fix it only in a new candidate experiment version rather than weakening the oracle.
