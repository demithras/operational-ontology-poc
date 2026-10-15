# H27 — Decision provenance is tamper-evident across authority, policy and contract history

## Claim

A Paladin decision/action can be reconstructed from version-pinned evidence, authority, policy and contract lineage such that any post-hoc mutation, deletion, substitution or rebinding inside mutable stores is detected before the altered history can be accepted as the original justification.

## Strong null / rival

Versioned provenance is only convenient logging; an attacker with write access to a mutable history store can rewrite both the evidence and the story about why an effect was legitimate without reliable detection.

## Mechanism under test

Each governed decision binds content-addressed evidence and exact authority/policy/contract versions into a canonical provenance envelope whose integrity root is anchored outside the mutable evidence store; replay refuses or marks unresolved when any bound artifact fails verification.

## Primary falsifiers

- A tampered bound artifact is accepted as the original historical justification.
- Missing historical authority/policy silently falls back to current state.
- A later artifact can replace an earlier binding without detection.
- Integrity verification produces material false positives on untampered histories under the frozen canonicalization rules.

## Experiment

Mutation and replay experiment over historical provenance bundles with an independent integrity anchor and immutable expected bindings.

1. Freeze canonical serialization, binding rules and trust-root placement.
2. Generate valid decision histories and anchor their provenance roots.
3. Apply single and compound mutations to evidence, authority, policy, contract and ordering.
4. Attempt replay, explanation and action continuation from mutated bundles.
5. Verify untampered controls reconstruct identically.
6. Inject fallback-to-current, digest-omission and rebinding mutants.

## Independent oracle

Immutable mapping of decision ids to canonical artifact digests and an independent verification root unavailable to the mutable history store under test.

## Fair baseline

Strong conventional append-only/event-log plus content-addressed artifacts and equivalent external integrity anchor.

## Stop rule

- If integrity depends on the same trust domain as the mutable history, do not claim tamper evidence; redesign the trust split or reject.
