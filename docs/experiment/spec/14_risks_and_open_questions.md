# 14 — Risks, Open Questions, and Decision Points

## R1 — RDF may not be the causal source of value

The strongest benefits may come from decision-as-data, policy-as-code, authorization, durable execution, CDC/reconciliation, and version discipline.

A relational baseline may reproduce most benefits.

**Response:** A/B experiment deliberately retains these good practices in the baseline.

## R2 — Too many components can predetermine failure

RDF4J + Kafka + Debezium + Temporal + OPA + OpenFGA + PostgreSQL is a large local stack.

**Response:** build incrementally; final reference mode uses full stack, but early phases do not.

## R3 — SHACL used outside its best role

The source thesis discusses SHACL gates broadly. Some business rules are better represented in policy code than graph constraints.

**Response:** explicitly separate conformance, authority, and contextual policy. Record rules' canonical owner.

## R4 — Historical authorization replay semantics

Question:

> Should replay prove that the actor *was authorized according to historical model + historical relationship tuples*, or only record the historical authorization result?

Strong replay requires historical tuples/context too.

**POC decision:** preserve enough authorization input/relationship snapshot or immutable result evidence to independently reproduce selected authorization cases.

This deserves an ADR during implementation.

## R5 — Evidence snapshot size

Full graph snapshots are simple but expensive.

**Candidate designs:**
1. named immutable graph per decision;
2. Merkle/content-addressed fact set;
3. source offsets + immutable event log + reconstruction;
4. hybrid.

**POC preference:** hybrid manifest with hashes + immutable required facts, then test reconstruction.

## R6 — Event log is not necessarily full history

Debezium depends on retained DB/WAL history and Kafka retention.

**POC requirement:** experiment-owned history must be retained long enough to replay. Do not claim replay from WAL that has been deleted.

## R7 — Ontology and source truth divergence

Ontology must not become an unqualified source of truth for source-owned properties.

**Response:** provenance + explicit authoritative source per property + reconciliation.

## R8 — Projection semantics can drift

Hot SQL views may implement logic that differs from graph semantics.

**Response:**
- version projection code;
- derive from canonical rules where feasible;
- differential projection tests;
- rebuild tests.

## R9 — Performance target is hardware-specific

The p95 targets are local experiment contracts, not universal claims.

**Response:** record environment and compare baseline on same hardware.

## R10 — "Six months later" cannot literally wait six months

The POC simulates elapsed governance evolution by creating old decisions under V1, migrating to V2/V3, and replaying them.

This tests semantic/time-version separation, not physical media longevity.

## R11 — AI evaluation may distract

LLM nondeterminism can obscure infrastructure failures.

**Response:** AI is optional final phase and is tested for safety-boundary robustness, not used as proof of core architecture.

## R12 — Fair baseline can become ontology in disguise

If relational baseline adds a generic entity-relation model, versioned semantic contracts, and provenance graph, it may converge architecturally toward the ontology variant.

That is itself an informative result. Record when the boundary becomes semantic rather than technological.

## Open decision: RDF4J vs alternative RDF store

Reference: RDF4J because SHACL transaction validation is directly relevant.

Alternatives may include Jena/Fuseki or Oxigraph, but substitution needs:
- SHACL behavior evaluation;
- transaction semantics;
- local operational simplicity;
- replay implications.

## Open decision: Kafka vs lighter event transport

Reference uses Kafka because Debezium integration and durable replay are well understood.

A lighter transport is acceptable for development but not final claims unless it preserves required delivery/order/replay semantics.

## Open decision: Temporal action compensation semantics

Not every external action is safely reversible.

Action contracts must specify:

```text
compensatable
non_compensatable
manual_recovery_required
```

Never invent compensation merely to make the workflow look complete.

## Open decision: historical policy explanation

Store:
- OPA input hash/full input where appropriate;
- output;
- policy bundle hash;
- reason/obligation structure.

The POC should determine whether bundle + input is sufficient for deterministic historical reproduction.

## Open decision: inference

Avoid large OWL reasoning scope initially.

Use only inference needed for the scenario and distinguish:
- observed;
- inferred;
- derived;
- asserted.

Inference rules themselves are versioned if they affect decisions.
