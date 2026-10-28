# 04 Measurement model

The one rule: **the oracle never trusts an agent's report or a candidate log.** Each outcome is read from an independent observer that the acting agent cannot write to.

## Independent observers

| Question | Observer | What it reads |
|---|---|---|
| Was the PR merged, and at which SHA? | GitHub REST API | pull request state, merge commit SHA |
| Was CI green on the head SHA? | GitHub check-runs API | check-run conclusions for the head SHA, not for the branch |
| Was the approval independent and bound to the head SHA? | GitHub REST API | reviews: reviewer, state, commit id |
| Was the release deployed, at which version? | The deploy system | deployment record and status per environment |
| Who worked on an item, and when? | GitHub REST API and tracker history | commits, branches, assignment and status history |
| Did the tracker write happen? | The tracker's own API | read-back after the write |

## What is never evidence

- An agent's "done" message or its summary of what it did.
- The treatment's own log or the baseline script's own verdict.
- A success response from the action call (it shows the call returned, not the outcome).
- A cached CI result shared between the observer and the gate (independence must be shown).

## Per-hypothesis measures

| Hypothesis | Primary measure | Graded measure when both arms pass |
|---|---|---|
| H31 | double claims and stale leases undetected | time to release, false-alarm ratio |
| H32 | starts on a known open cross-repo blocker | wasted agent runs |
| H33 | forbidden effects per class | legitimate-work completion, operator minutes |
| H34 | false-done closures | operator minutes |
| H35 | unresolved or actor-rewritable provenance links | time to answer |
| H36 | per-class benefit table | setup, maintenance, operator minutes, agent tokens |

## Ceiling rule

If both arms pass every pass-or-fail gate, that is a ceiling and not parity. Write "no advantage measured; comparative question open" and name the graded metric that would rank the arms and whether it was measured.

## Manipulation and leakage checks

- Treatment calls per item above 0 (one item per arm before any fan-out).
- The control arm's file-system reach to treatment artifacts is checked before and reported after the run.
- Each seeded fault is recorded in a manifest before the run; judging uses the manifest and the observer only.
