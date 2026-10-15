# H24 — Delegation, revocation and expiry remain authoritative under concurrency

## Claim

The authority subsystem can issue, delegate, attenuate, expire and revoke capabilities so that every effect is evaluated against the currently legitimate authority chain, with no stale-capability window that silently creates an unauthorized effect.

## Strong null / rival

Delegation is safe only in static examples; revocation, expiry, nested delegation and concurrent in-flight work create unavoidable stale-authority effects or ambiguous ownership.

## Mechanism under test

Capabilities are version-bound, scope-attenuating and non-amplifying; effect eligibility includes an authority freshness rule, and revocation/expiry changes invalidate stale paths before commitment or force explicit unresolved/revalidation state.

## Primary falsifiers

- Any delegated capability is broader than its parent authority.
- Any effect commits after the frozen revocation/expiry boundary using only a stale authority path.
- A concurrency schedule allows both revoke and a conflicting stale commit to be treated as legitimate.
- An authority cycle or ambiguous path grants an effect without an explicit resolution rule.

## Experiment

State-machine experiment over nested delegation, attenuation, expiry, revocation, approvals, concurrent execution and replay.

1. Freeze authority-clock semantics and the exact commit boundary at which revocation/expiry becomes effective.
2. Generate authority DAGs, nested delegations, expirations and action attempts.
3. Generate revoke/execute races and crash/retry schedules.
4. Compare legitimacy with an immutable reference authority model.
5. Measure safe progress separately from safety so global serialization cannot masquerade as a successful security design.
6. Inject non-attenuating delegation, stale-cache and revoke-race mutants.

## Independent oracle

Immutable reference authority DAG with explicit scope intersection, version, logical clock, revocation boundary, expiry and deterministic conflict semantics.

## Fair baseline

Conventional short-lived capability/token system backed by a centralized policy/authorization service with the same freshness and availability objectives.

## Stop rule

- If deterministic revocation cannot coexist with useful safe progress in the frozen envelope, reject/narrow before adding richer constitutional authority.
