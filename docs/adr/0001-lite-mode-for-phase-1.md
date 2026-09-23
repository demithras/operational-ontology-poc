# ADR 0001 — Lite mode for Phase 1

**Status:** accepted
**Date:** 2026-09-23

## Context

`docs/experiment/spec/12_implementation_plan.md` requires Phase 1 to deliver a
pure domain model (`reference_model/`) with deterministic transitions,
invariants, the canonical incident, and a Hypothesis state machine, built in
a vertical slice *before* any source system, semantic core, gate service, or
durable action runtime exists.

`docs/experiment/spec/02_scope_and_non_goals.md` defines two operating modes:
**reference mode** (full local architecture — RDF4J, PostgreSQL, OpenFGA,
OPA, Temporal, Kafka, Debezium, OpenTelemetry) and **lite development mode**
(rdflib/pySHACL, PostgreSQL, in-process fake event bus, synchronous
executor), and states lite mode "must never be used for final
fault-tolerance, CDC, ordering, replay, or latency claims."

## Decision

Phase 1's reference model (`reference_model/state.py`, `transitions.py`,
`invariants.py`, `derive.py`) runs in **lite mode, taken to its logical
extreme: pure Python, in-process, with no infrastructure at all** — no
RDF4J, no PostgreSQL, no OpenFGA/OPA service, no Temporal, no Kafka/Debezium,
no network, and no LLM. It is a synchronous, frozen-dataclass state machine
that acts as the test oracle described in
`docs/experiment/spec/08_test_strategy.md` ("Level 0 — Pure reference
model").

Gates that will later be externalized to real services (OpenFGA
authorization, OPA policy, SHACL conformance) are modeled here as **pure
functions with the same decision boundaries** (ALLOW / DENY /
REQUIRES_APPROVAL / INSUFFICIENT_EVIDENCE / INVALID_CONFORMANCE), not as
stubs that call out to anything. Execution and observation (WMS call, CDC
correlation) are collapsed into a single synchronous step that records the
effect as "expected-and-observed" — this repository does **not** claim to
model Change Data Capture, network partition, or durable-workflow recovery
in Phase 1. That is explicitly Phase 6 (`services/action_worker`,
`services/reconciliation`) per the implementation plan.

## Alternatives

- **Build reference mode from day one (RDF4J + Postgres + OpenFGA + OPA +
  Temporal via Docker Compose).** Rejected for Phase 1: it would front-load
  infrastructure before the domain rules themselves are validated, inverting
  the "vertical slices" build order the implementation plan calls for, and
  would make the oracle depend on the very services it is meant to validate
  independently.
- **Use rdflib/pySHACL for the gates even in Phase 1** (spec's literal "lite
  mode"). Rejected for Phase 1 specifically: `08_test_strategy.md` defines
  Level 0 as "no network, DB, RDF, or LLM" and explicitly scopes the pure
  model to *domain rules, not implementation details*. Introducing rdflib
  here would blur Level 0 (pure oracle) with Level 1 (contract/unit tests
  against real SHACL shapes), which are deliberately separate layers.

## Hypotheses affected

H2 (gates prevent invalid effects), H5 (concurrency preserves invariants),
H10 (deterministic architecture works without AI), H14 (semantic openness
and operational closure can coexist) are all testable in Phase 1 form, at
the domain-rule level, using this pure model.

H3 (closed-loop truth beats command success), H4 (durable actions survive
faults), H6 (hot-path latency), H7/H8 (replay/versioning across real
migrated contracts), H9 (agent bounded by *server-side* controls), H12
(independent reality-check via real CDC) are **not** resolvable in Phase 1
lite mode and remain PENDING until the corresponding infrastructure phase
lands. Phase 1's `execute_transfer` intentionally sets `OBSERVED_SUCCESS`
synchronously as a stand-in for the future CDC-based reconciliation — this
must not be read as evidence for H3/H12; those require the real Debezium
path (Phase 6).

## Experimental equivalence

Phase 1's gate functions preserve the *decision boundary semantics* required
by H2/H14 (same named outcomes, same evidence-closure requirement, same
gate-ordering contract from `06_decision_and_action_runtime.md`) but not the
*enforcement mechanism* (no real OpenFGA/OPA/SHACL evaluation engine). This
is sufficient for testing domain-rule correctness and for mutation/bug
detection at the rule level, but insufficient on its own to support H2's
"enforceable trust boundary" claim in the final report — that claim requires
Phase 5's real gate services to also pass the same negative suite.

## Consequences

- Phase 1 can be fully tested with `pytest` and `hypothesis`, no `docker
  compose up` required, keeping the inner loop fast.
- The reference model becomes the oracle that later phases' component/
  integration/stateful tests differentially compare against
  (`08_test_strategy.md`, "Differential testing").
- Any hypothesis conclusion drawn purely from Phase 1 results must be
  labeled provisional/lite-mode in `experiments/exp-000/manifest.yaml` and
  re-verified once the corresponding reference-mode service exists, per
  `02_scope_and_non_goals.md`'s lite-mode restriction.
