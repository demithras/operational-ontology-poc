# H31 — Leases catch double claims and stale claims

## Claim

A lease service in front of the work queue (invariants C1 single ownership and C2 liveness) detects and prevents double claims (F1) and detects and releases stale claims (F2) strictly better than the conventional stack of `bd ready` plus GitHub assignees, measured by an independent observer of who actually worked on each item.

## Strong null

The conventional coordination stack (beads status in_progress plus assignee, bd ready, GitHub assignees, and a reconciliation script of equal effort) catches double and stale claims as well as the lease service does; a lease adds machinery without a measurable gain.

## Rivals

- The conventional stack already does this: bd update --status=in_progress with an assignee, plus a reconciliation script, gives single ownership and stale detection within the same bound.
- The lease advantage appears only because the baseline reconciliation script was written with less effort than the lease service.
- The lease service catches faults only by refusing more legitimate claims (higher false-alarm rate), not by being more correct.
- Double claims are rare in practice with two agents and one repo, so the pilot cannot tell the arms apart.

## Mechanism under test

An atomic claim operation grants one lease per work item with an expiry and a heartbeat; a second claim on a live lease is refused and a lease without heartbeat past the frozen bound is released by the service, not by the agent that holds it.

## Primary falsifiers

- The conventional arm detects and resolves every seeded F1 and F2 fault within the frozen bound, so there is nothing for the lease to add.
- The lease arm lets any double claim or any unreleased stale lease through.
- The lease arm's gain disappears when the baseline reconciliation script gets equal effort and the same heartbeat input.

## Experiment

Seed F1 and F2 into the same sequence of work items for both arms, run the same two worker agents, and let an independent observer (source-host API: who pushed to which branch and when, tracker history) judge ownership and release time.

1. Freeze the seeded sequences, the stale bound and the observer before any run.
2. Run the baseline arm first (beads in_progress, assignee, bd ready, equal-effort reconciliation script) and record detection rate, time to release and false alarms.
3. The comparative thresholds are already fixed by the author (thresholds.json, comparative_basis); the baseline pilot only checks for headroom and does not change them.
4. Pilot one item per arm, check that the treatment made lease calls (manipulation check) and that the control arm could not read treatment artifacts through the file system.
5. Run both arms on at least the pilot minimum of seeded faults per class (thresholds.H31.min_seeded_faults_per_class).
6. Judge every item by the observer, never by an agent's report or the arm's own log; report a per-class table and the cost of each arm.

## Independent oracle

Independent observer reading the source-host REST API (commits and branches by author and time) and tracker history to reconstruct, per item, which agents did work and when each lease or assignment ended; it imports no code from either arm.

## Fair baseline

beads (bd update --status=in_progress with assignee, bd ready, dependencies) plus GitHub assignees plus a reconciliation script of equal effort to the lease service, with the same heartbeat information available.

## Stop rule

- If the baseline catches every seeded F1 and F2 fault in the pilot, record the result and stop H31; do not add faults after seeing the outcome.
