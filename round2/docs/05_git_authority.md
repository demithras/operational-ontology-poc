# 05 — Git authority contract

For the first self-hosting experiment:

```text
Git = canonical authority
EOO Project Ontology = derived executable projection and governed mutation surface
```

## Required properties

1. A clean rebuild from Git reproduces the same canonical Project Ontology state hash.
2. Every durable Project Ontology action that changes research state is materialized as a versioned Git change.
3. The ontology cannot silently accept a stale write over a newer Git version.
4. Concurrent compatible changes may merge; conflicting changes must surface an explicit conflict.
5. Ephemeral runtime state is clearly marked and never confused with canonical project state.
6. Historical verdicts/evidence remain bound to the commit/version under which they were created.

The purpose is to avoid creating a second opaque database that competes with the repository for truth.
