# 02 Domain model

Agents do IT work across several repositories. Two problems follow: **coordination** (who works on what, when) and **control** (what an agent may do to the world, and what counts as true).

## Invariants

| ID | Name | Meaning in one line |
|---|---|---|
| C1 | Single ownership | One live lease per work item. |
| C2 | Liveness | A stale lease is detected and released within a bound. |
| C3 | Dependency respect | No start on an item whose cross-repo blocker is open. |
| K1 | Effect authority | Merge, deploy, push to default and tracker writes only within granted authority. |
| K2 | Review separation | No self-approval or self-merge without independent approval. |
| K3 | Green gate | No merge on red or missing required checks for the merged head SHA. |
| K4 | External truth | An item closes only when an independent observer confirms the outcome. |
| K5 | Provenance | Every effect links to item, agent, authority, policy version, evidence and outcome. |

Full statements and `violated_when` text are in `model/agent_ops_invariants.json`. Faults F1-F10 are in `model/fault_classes.json`. Gated actions (`merge_pr`, `deploy_release`, `push_default_branch`, `close_work_item`, `write_external_tracker`) are in `model/actions.json`.

## The loop and the split

```text
            COORDINATION (C1-C3)                    CONTROL (K1-K5)
   ┌────────────────────────────────┐   ┌─────────────────────────────────────────┐
   │ work item ──► lease ──► start  │   │ Decision ─► Authorization ─► Policy      │
   │    ▲            │        ▲     │   │                                  │       │
   │    │ release    │ heartbeat    │   │                               Approval   │
   │    └── stale ◄──┘        │     │   │                                  │       │
   │                  cross-repo    │   │  Observed Outcome ◄──────── Action       │
   │                  blocker view  │   │       │ (independent observer)           │
   └───────────────┬────────────────┘   └───────┼─────────────────────────────────┘
                   │ agent starts work          │ effect confirmed ─► item closes (K4)
                   └─────────────► agent ───────┘          and provenance links (K5)
```

## Where each fault lands

| Side | Faults | Invariants |
|---|---|---|
| Coordination | F1 double claim, F2 stale lease, F3 blocker ignored | C1, C2, C3 |
| Control | F4 false done, F5 self-merge, F6 merge on red, F7 unapproved deploy, F8 forged approval, F9 scope creep, F10 tracker write | K1-K5 |

The conventional arm gets the same agents and the same seeded faults, so the comparison is about the architecture, not the workload.
