# ADR 0002 — Debezium CDC ingestion built in Phase 3, not deferred to Phase 6

**Status:** accepted
**Date:** 2026-09-23

## Context

`docs/experiment/spec/12_implementation_plan.md` places "durable action
runtime (Temporal, WMS action, idempotency, CDC, reconciliation)" in
Phase 6, which reads as though CDC belongs there. But CDC in this
architecture (`docs/experiment/spec/04_architecture.md`) plays two distinct
roles that are easy to conflate:

1. **Observation ingestion** — the primary path by which ERP/MES/WMS
   committed row-level changes become RDF facts in the semantic core
   (component diagram: `ERP/MES/WMS -> Kafka -> Ingestion/identity resolver
   -> RDF4J`). Every fact the semantic core holds about source systems
   arrives this way, from the very first write onward.
2. **Reconciliation observation** — Phase 6 compares an action's *expected*
   effect (what a decision proposed) against the *observed* effect (what
   CDC actually reports), to distinguish `OBSERVED_SUCCESS` from
   `DIVERGED`/`OUTCOME_UNKNOWN`.

Phase 6 needs (2), which depends on (1) already existing and being
trustworthy (idempotent under duplicate delivery, correctly ordered by
source version/LSN not wall clock, provenance-tagged). If CDC ingestion is
first built in Phase 6, Phase 6 would have to build both the general
ingestion pipeline *and* the reconciliation logic that consumes it in one
phase, and Phases 3-5 (semantic core, projections, decision gates) would
have no real observed facts to operate against — they would either fake
data or ingest through a throwaway path that gets rewritten in Phase 6,
which risks exactly the kind of scaffolding-that-becomes-permanent this
project's honesty rules (`docs/experiment/briefs/common.md`) exist to
prevent.

## Decision

Build Debezium + Kafka + the CDC-consuming `services/ingestion` pipeline
now, in Phase 3, as the *only* path by which observed source facts enter
the RDF4J semantic core (manual seed/test writes aside). Phase 6 reuses
this exact pipeline unchanged for reconciliation; it does not stand up a
second, different observation path.

## Alternatives

- **Defer CDC to Phase 6 as planned, ingest via polling/REST in Phase 3.**
  Rejected: a REST-polling ingestion path would have different ordering,
  duplication, and staleness characteristics than CDC, so Phase 6 would
  either have to replace it (rewrite risk, wasted Phase 3 work) or keep
  two parallel ingestion mechanisms (violates "one canonical owner" spirit
  of `05_ontology_and_contracts.md`). It would also mean Phases 3-5 could
  never legitimately exercise F18-F21/F35/F37/F38 (CDC delay, duplication,
  reorder, clock skew, manual DB edits, poison messages) until Phase 6,
  leaving those failure modes untested against the actual gate/projection
  code they are meant to protect.
- **Defer CDC entirely, use direct synchronous writes from the identity
  resolver into RDF4J.** Rejected: this would make the semantic core an
  active puller of source state rather than a passive observer, contrary
  to `04_architecture.md`'s "the ontology is not allowed to mutate their
  databases directly" and the observed/inferred/derived/asserted
  distinction in `05_ontology_and_contracts.md`, which requires facts to
  carry real source-event provenance (LSN/offset), not a resolver's own
  read timestamp.

## Hypotheses affected

H3 (real-world outcome observation via CDC, not command-path trust) and
H12 (independent reality-check) become testable starting in Phase 3
instead of Phase 6, since the CDC path they depend on exists and is
already exercised by the failure matrix (F18-F21, F35, F37-F39) at the
semantic-core level. H1/H2/H5 (decisions/gates) are unaffected — they are
not implemented yet. No hypothesis is made *worse* off; several become
testable earlier than the plan implied.

## Experimental equivalence

This does not substitute a reference-stack component — it builds the
reference-stack component (Debezium + Kafka CDC) at the point in the build
order where its consumers (RDF4J semantic core) first exist, rather than
waiting for its second consumer (reconciliation) to also be ready. The
mechanism used in Phase 6 is byte-for-byte the same pipeline, so no
experimental-equivalence gap is introduced.

## Consequences

- Phase 3 is materially larger than the brief's phase table implied
  (Kafka + Debezium Connect + a real consumer service), but Phase 6 is
  correspondingly smaller (reconciliation logic only, no new ingestion
  path).
- `docker-compose.yml` carries the full CDC stack from Phase 3 onward;
  `wal_level=logical` was already set in Phase 2 for exactly this reason,
  so no data-losing reset is needed.
- Later phases (4, 5) can build hot projections and decision gates against
  real observed RDF facts with real provenance instead of hand-seeded
  graph fixtures, which is a stronger basis for their own tests.
- `docs/experiment/spec/12_implementation_plan.md`'s phase table is
  descriptive of *intent*, not a hard contract; this ADR is the
  version-controlled record of the deviation, per
  `13_repository_contract.md`'s ADR requirement.
