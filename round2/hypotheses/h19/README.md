# H19 — Git authority and executable ontology can coexist without split brain

## Claim

With Git as canonical authority, Project Ontology can rebuild deterministically, execute governed changes through versioned Git mutations, detect stale/conflicting writes and preserve historical bindings without becoming a competing source of truth.

## Strong null/rival

Making the ontology executable creates a second mutable truth store whose state can diverge from Git or lose concurrency/history semantics.

## Why this exists

Treat ontology state as a deterministic projection of versioned Git artifacts and require every canonical mutation to carry a base version and produce a Git commit/change record.

## Primary falsifiers

- Same Git commit rebuilds to different canonical state.
- Canonical ontology state changes without a Git-visible change.
- Generated stale write causes a lost update.
- Historical evidence silently rebinds to a later contract/version.

## Python Hypothesis role

State machine generates commit DAG operations, base revisions, Project Actions, rebuilds, merges and conflicts.

## Stop rule

- If Git and ontology cannot maintain one-way canonical authority without special manual reconciliation, reject before adding more self-hosted actions.
