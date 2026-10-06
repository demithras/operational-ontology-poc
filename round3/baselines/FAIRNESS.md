# Strong conventional baseline fairness contract

H30 is invalid if the baseline is a strawman.

The baseline is a conventional typed relational/event architecture, but it receives equivalent engineering quality and obvious best-practice controls:

- strong workload identity and authenticated service identities;
- RBAC/ABAC/ReBAC or an equivalent policy/authorization engine;
- typed request/resource/action schemas and code generation where useful;
- server-side effect authorization, not client-only tool hiding;
- least-privilege service/adapter credentials;
- idempotency, retries and durable workflow semantics;
- versioned policy/authority configuration;
- append-only/content-addressed provenance plus the same class of independent integrity anchor used by the candidate;
- independent reconciliation/observation where the candidate receives it;
- observability, explicit dependency failure and deterministic recovery objectives;
- comparable test/mutation/fault engineering effort.

Shared low-level libraries are allowed and often preferable when they remove implementation-quality confounds. The comparison is architectural behavior, not duplicated programmer mistakes.

Do not count candidate compiler/toolchain/security glue as free while counting equivalent baseline glue. Do not omit an obvious baseline control merely because it weakens the Paladin advantage; add it before freeze or invalidate/refreeze if discovered later.

## Dual track (author decision 2026-10-06)

The conventional variant is not assembled at H30: it is built in parallel with Paladin from Gate 1 onward, by a separate
builder working from the protection specification, and it must satisfy the same operational requirements, attacks,
oracles and quality bar. Every Paladin protection is paired with the strongest reasonable conventional equivalent in
`protocol/HARDENING_LEDGER.jsonl` before the gate that measures it, and an independent equivalence audit runs before
each measurement. If Paladin fails, the conventional implementation is the product path. See `protocol/DUAL_TRACK.json`.
