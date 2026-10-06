# H28 — Byzantine adapters cannot become hidden authorities or truth oracles

## Claim

An external adapter may be unavailable or malicious, but it cannot mint governance authority, exceed its scoped effect capability, or make the Engine record reconciled success solely by asserting that an external effect occurred.

## Strong null / rival

Adapters are an unavoidable trusted-computing-base escape hatch: once an integration is compromised it can smuggle policy decisions, alter action targets or lie about outcomes in ways the generic Engine cannot distinguish.

## Mechanism under test

Governance stays in the Engine; adapters receive attenuated action-specific credentials and a byte-exact provenance envelope, while outcome truth comes from a separately scoped observation path or remains explicitly UNKNOWN/DIVERGED.

## Primary falsifiers

- An adapter creates an effect outside its delegated external capability scope.
- An adapter lie alone produces reconciled success.
- Required authority/policy semantics move into adapter code and the Engine accepts the outcome without equivalent generic enforcement.
- Retry/replay causes duplicate external effect beyond the declared action semantics.

## Experiment

Byzantine adapter harness with separate effect and observation truth stores, differential checking against generic Engine expectations.

1. Freeze adapter credentials, external resource scopes and independent observation topology.
2. Run honest controls to prove effects and observations are measurable.
3. Inject false success/failure, target substitution, duplicate delivery, omission, delay and governance logic into adapters.
4. Measure external ground truth independently from adapter responses.
5. Audit adapter code/import closure for authority/policy semantics.
6. Inject observation-coupling and idempotency mutants.

## Independent oracle

Independent external world/effect ledger plus a separately scoped observation model; neither trusts the action adapter response.

## Fair baseline

Conventional integration service with scoped credentials, idempotency and independently implemented reconciliation under the same external world.

## Stop rule

- If observation cannot be made meaningfully independent for an effect class, the system must expose that effect as lower-confidence rather than claim closed-loop truth.
