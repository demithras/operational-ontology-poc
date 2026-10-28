# Author decisions, 2026-10-28

Recorded as given by the author on 2026-10-28. They bind the draft pack until the author changes them in a new dated file.

## (a) Round 4 domain

Round 4 is **coordination and control of AI agents working across several IT projects**. It replaces the earlier Attractor-game plan as Round 4. The status of the game for Round 5 and later is undecided.

## (b) Pilot scope

- 2 repositories
- 2 agents
- 1 gated action: an agent merges its own PR (`merge_pr`)

The round may stop after the pilot (see `docs/03_pilot_design.md`).

## (c) Store

Relational, as in Round 1 H11. No RDF4J, Kafka or Debezium unless a hypothesis needs them and says why in its contract.

## (d) Build relation

- Coordination builds on beads (the `bd` task tracker).
- Control borrows the contracts and patterns of the Round 1-3 proof of concept (gated actions, authority, provenance, adapter boundary).

## Not decided here

Everything in `OPEN_QUESTIONS.md`. The pack cannot be frozen while those questions are open.
