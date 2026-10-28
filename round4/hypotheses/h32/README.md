# H32 — Cross-repo blockers are surfaced before an agent spends a run

## Claim

A cross-repository dependency view (invariant C3 dependency respect) surfaces an open blocker in another repository before an agent starts an item (fault F3), and does so strictly better than beads dependencies inside each repository.

## Strong null

Per-repository beads dependencies, possibly with cross-references written by hand, already stop agents from starting items with open cross-repo blockers as often as the cross-repo view does.

## Rivals

- The conventional stack already does this: beads dependencies plus a cross-repo reference convention plus a small script that reads both trackers gives the same surfacing.
- The advantage comes only from seeding blockers the baseline convention was never told about (an unfair seed).
- The cross-repo view surfaces blockers late or noisily, so agents still waste runs.
- With two repos the cross-repo graph is too small to matter; the pilot cannot show a gain.

## Mechanism under test

A single dependency graph spans all repositories; before an agent is offered an item, the graph is checked for open blockers in any repository and the item is withheld with the blocker named.

## Primary falsifiers

- The conventional arm starts 0 blocked items across all seeded F3 cases.
- The treatment starts any item whose cross-repo blocker was open and knowable at the start.
- The treatment's surfacing disappears when the baseline gets an equal-effort cross-repo script.

## Experiment

Seed cross-repo blockers (open, then later closed) in both arms, offer the same items to the same agents, and let an independent observer decide from source-host and tracker state whether the blocker was open when work started.

1. Freeze the seeded blocker set, including blockers that close mid-run and blockers that were never written down as a dependency anywhere in the baseline arm's convention.
2. Run the baseline arm first and record starts on open blockers and wasted runs.
3. The comparative thresholds are already fixed by the author (thresholds.json, comparative_basis); the baseline pilot only checks for headroom and does not change them.
4. Pilot one item per arm; check treatment graph calls per item and the file-system reach of the control arm.
5. Run both arms at the pilot minimum (thresholds.H32.min_seeded_faults_per_class).
6. Judge start-versus-blocker order by the observer from timestamps in the source host and tracker, never from agent reports.

## Headroom rule

The comparative bar of this contract is read through `thresholds.headroom_rule`: the absolute bar applies while the baseline rate is at most 0.80; above it the treatment must close at least 50% of the baseline's misses, (treatment - baseline) / (1 - baseline); at a baseline of 0.95 or more the class is recorded as CEILING: no advantage measured, never REJECTED (verdict INCONCLUSIVE with reason "CEILING"). A fixed +20 bar is unreachable by construction above 0.80.

## Independent oracle

Independent observer reconstructing, from source-host and tracker timelines, whether each blocker was open at the instant work on the blocked item started; no code from either arm is imported.

## Fair baseline

beads dependencies inside each repository, plus a cross-repo reference convention and an equal-effort script that reads both trackers, plus GitHub issue links.

## Stop rule

- If the baseline withholds every seeded blocked item in the pilot, record the result and stop H32.
