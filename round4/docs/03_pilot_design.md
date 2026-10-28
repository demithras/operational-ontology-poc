# 03 Pilot design

The round is pilot-first. The pilot is small on purpose; it may be the whole round.

## Scope

| Item | Pilot value |
|---|---|
| Repositories | 2 |
| Agents | 2 |
| Gated action | 1: an agent merges its own PR (`merge_pr`) |
| Arms | conventional stack (baseline) and treatment (leases, dependency view, control gate, observer-confirmed close, provenance) |
| Seeded faults | at least the pilot minimum per class in `protocol/thresholds.json` (marked pilot) |

Faults most relevant to the one gated action: F5 self-merge, F6 merge on red or stale-head CI, F8 forged or replayed approval, F4 false done. Coordination faults F1-F3 use the two repositories and two agents directly.

## The two pilot questions

1. **Does the conventional stack, fully configured per `baselines/FAIRNESS.md`, catch everything the pilot seeds?** Measured by the independent observer, not by agent reports.
2. **For the faults the baseline misses, does the treatment catch them, and at what cost** (legitimate work refused, operator minutes, agent tokens, setup effort)?

## Order of work

```text
 freeze pack (Stage A) ─► baseline pilot ─► record numbers ─► set comparative thresholds
        ─► freeze thresholds (Stage B) ─► manipulation check, 1 item per arm
        ─► treatment run ─► observer judges ─► verdicts and frontier
```

## Stop rule

If the baseline catches everything the pilot seeds, record the result and stop. Write "no advantage measured" for H31-H35, record H36 as REJECTED for the tested scope (parity), and do not add faults or widen the scope afterwards to find a gap. A clean rejection is a successful result.

## What the pilot cannot show

- Behavior at more than 2 repositories or 2 agents.
- Gated actions other than merge (deploy, push to default, tracker write) unless the author extends the scope in a new dated decision.
- Long-term maintenance cost; it is estimated from logged hours only.
