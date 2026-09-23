# 00 — Thesis Under Test

## Source thesis

The source video argues that a knowledge graph becomes operational infrastructure only when it can participate in a live, accountable decision loop rather than merely model semantic truth.

The thesis can be decomposed into six engineering claims:

1. **Decision as first-class data.** A decision must be explicitly represented with actor, evidence, policy basis, time, action, and outcome.
2. **Explicit gates.** Invalid state transitions and insufficient decision context must be rejected before harmful writes occur.
3. **Operational speed.** Semantic richness alone is insufficient; urgent flows need fast projections or snapshots rather than arbitrary deep graph traversal on every request.
4. **Versioned contract.** Ontology, shapes, policies, and action semantics evolve and must be versioned with migration discipline.
5. **Replayability/provenance.** Historical decisions must remain interpretable under the rules and evidence that existed at the time.
6. **Closed feedback loop.** Data enters, identities align, a decision is made, an action changes an external system, the result is observed, and the next decision starts from the changed world.

The POC will not test Palantir as a company or reproduce Foundry/AIP as products. It tests whether this *behavioral architecture* can be reproduced locally with open-source components.

## Strong formulation

> An operational ontology is a versioned semantic and executable contract that links observed world state to governed decisions, authorized actions, observed outcomes, and replayable provenance.

For this POC:

```text
OperationalOntology
  = WorldModel
  + DecisionModel
  + ActionModel
  + Conformance
  + Authority
  + Policy
  + Provenance
  + Feedback
  + Versioning
  + HotPath
```

## Minimal operational loop

```text
WORLD
  |
  | observe / CDC
  v
SOURCE SYSTEMS
  |
  v
SEMANTIC CORE
  |
  +--> HOT PROJECTION
  |
  v
DECISION
  |   actor + evidence snapshot + policy version
  v
AUTHORIZATION
  v
POLICY
  v
CONFORMANCE / TRANSITION GATE
  v
ACTION EXECUTION
  |
  | external side effect
  v
WORLD'
  |
  | independently observed
  v
OUTCOME + RECONCILIATION
  |
  v
PROVENANCE / MEMORY
```

## What would *not* prove the thesis

The following are explicitly non-evidence:

- a nice RDF graph;
- an LLM that can answer questions over the graph;
- an action button that calls an API;
- a successful happy-path transfer;
- an audit log containing only timestamps and usernames;
- a graph whose old decisions can no longer be interpreted after schema evolution;
- a system that marks an action successful because its own HTTP request returned `200`;
- a system that relies on the LLM to obey policy;
- a demo with no baseline for comparison;
- a demo that cannot survive duplicate messages, concurrency, crashes, or stale evidence.

## Falsification criteria

The thesis is weakened or rejected for this POC if any of the following is true:

1. A forbidden or structurally invalid action can produce an external side effect.
2. Duplicate/retried execution can create duplicate business effects.
3. A successful command is recorded as a successful outcome when the external world does not actually reflect it.
4. A historical decision cannot be reconstructed after ontology/policy/action evolution.
5. Hot-path latency fails the declared SLO under the declared local load.
6. The operational ontology produces no meaningful reliability, auditability, or change-management benefit compared with the simpler baseline, while adding substantial complexity.
7. Correctness depends on an LLM respecting prose instructions instead of hard system boundaries.
8. The system cannot distinguish observed facts, inferred facts, proposed actions, executed actions, and observed outcomes.
9. The ontology can represent a state that violates mandatory operational invariants after a committed governed write.
10. The implementation cannot explain exactly which contract versions governed a decision.

## Unit of evidence

Evidence is a repeatable experiment with:

- seed;
- initial world state;
- generated action/event sequence;
- relevant contract versions;
- observed outputs;
- pass/fail oracle;
- logs/traces;
- final world state hash.

A screenshot is not evidence.

## Scope of conclusion

Passing this POC would support only this conclusion:

> A small open-source stack can reproduce the essential operational-ontology behavior tested here.

It would **not** prove parity with Palantir Foundry/AIP in scale, UX, security certification, deployment tooling, governance depth, connectors, or enterprise operations.
