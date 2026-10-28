# 01 Inheritance from rounds 1-3

## What carries over

| From | What | How it is used |
|---|---|---|
| Round 1 | The governed loop Decision -> Authorization -> Policy -> Approval -> Action -> Observed Outcome | The control side (K1-K5) is this loop applied to merges, deploys and closures. |
| Round 1 | H11 lesson: test against a like-for-like baseline | Every contract has a conventional-stack rival and a fairness contract. |
| Round 1 | Relational store | Decided 2026-10-28: relational, no RDF4J, Kafka or Debezium unless a hypothesis needs them. |
| Round 2 | Function is not Action; Git as canonical authority | Only effects are gated; reads are free. |
| Round 3 H23 | Compromised agent stays effect-contained | H33 (control gate) reuses the containment idea. |
| Round 3 H24 | Delegation, attenuation, expiry, revocation | H31 leases are expiring, revocable grants. |
| Round 3 H27 | Tamper-evident decision provenance | H35 (provenance) reuses it. |
| Round 3 H28 | Adapter boundary: adapters are not authorities or truth oracles | H34 independent observers follow the same rule. |
| Round 3 method | Freeze, thresholds, two ledgers, mutation proof, dual track | Kept, with a single freeze and author-fixed comparative thresholds (see `protocol/preregistration.md`). |
| beads | Task tracker with dependencies and `bd ready` | The coordination arm builds on it; the conventional arm is built on it too. |

## What is dropped

- The Paladin class definition (P1-P6) as the organising frame; Round 4 uses C1-C3 and K1-K8.
- Attack classes A1-A10 and the survivability envelope of Round 3; Round 4 uses fault classes F1-F14.
- The Attractor game as Round 4 (R5+ status undecided).
- The manufacturing and project-ontology domains as test domains.
- Any attempt to reopen H11, H22 or H22w.

## What is new

- Coordination invariants (C1-C3) that Round 3 did not cover.
- The test subjects are real agents doing real repository work.
- A baseline pilot that checks headroom; comparative thresholds are author-fixed before any run.
- A value-of-information line per hypothesis and an explicit stop rule.
