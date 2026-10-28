# H34 — External truth: items close only on an independently observed outcome

## Claim

A work item closes only when an independent observer confirms the claimed outcome (K4: PR merged at the claimed SHA, CI green on it, deploy at the claimed version), so a false done (F4) never closes an item, and this beats agent self-report plus a human spot check.

## Strong null

Agent self-report plus a human spot check closes items as correctly as an independent-observer gate does; the false-done closure rate is the same.

## Rivals

- The conventional stack already does this: a required-check rule, a PR-linked close and a reconciliation script that reads the PR and CI state catch false done as well.
- The human spot check is strong enough at pilot volume; the advantage appears only at volumes the pilot does not reach.
- The gate catches false done only by closing fewer items (higher backlog), not by being more accurate.
- The observer and the agent share a failure mode (for example both read the same cached CI result), so the gate's confirmation is not independent.

## Mechanism under test

The treatment FORBIDS closing an item without observer confirmation; the baseline reconciliation script only DETECTS a false done after the fact. close_work_item requires the claimed outcome (PR, SHA, version) and re-reads it from the source-host API, the check-runs for the claimed SHA and the deploy system at close time; when the observer is unavailable the item stays open and the state is explicit, never closed.

## Predictions and graded metrics

- Forbid versus detect: the treatment prevents a false-done closure (false-done lifetime 0 s, `thresholds.H34.max_treatment_false_done_lifetime_seconds`); the baseline script detects it only after the false close, so its lifetime is above 0.
- False-done lifetime = seconds from false close to detection (0 when prevented). Downstream work on a false done = count of items or PRs started that depend on it; it must be lower in the treatment than in the baseline.
- Extra evidence: `false-done-lifetimes.json`, `downstream-work.json`.

## Primary falsifiers

- The baseline, with a reconciliation script of equal effort, closes 0 false-done items as well.
- Any false done closes in the treatment arm.
- The gate's detection advantage disappears when the baseline human spot check is given the same observer data the gate reads.

## Experiment

Script worker agents to report completion on seeded F4 cases mixed with truly done items; both arms decide whether to close; an independent observer reads the real PR, check-run and deploy state to say which closures were false.

1. Freeze the F4 case mix (three false-done forms plus truly done items) and the observer before any run.
2. Run the baseline arm first (agent self-report plus human spot check at the 10% sampling rate thresholds.H34.baseline_spot_check_rate, with a reconciliation script of equal effort) and record false-done closures and operator minutes.
3. The comparative thresholds are already fixed by the author (thresholds.json, comparative_basis); the baseline pilot only checks for headroom and does not change them.
4. Pilot one item per arm; check treatment observer calls per item and the file-system reach of the control arm.
5. Run both arms at the pilot minimum (thresholds.H34.min_seeded_faults_per_class per form).
6. Include an observer-outage condition to test the explicit unavailable state.
7. Judge every closure from the real source-host and deploy state, never from the agent's report or either arm's log.

## Independent oracle

Independent observer reading the source-host REST API (PR state and merge SHA), check-runs for the claimed SHA and the deploy system's deployed version; it never reads an agent's completion report.

## Fair baseline

Agent self-report plus a human spot check of 10% of closed items (thresholds.H34.baseline_spot_check_rate), strengthened with every plain control from baselines/FAIRNESS.md: required status checks, PR-linked close, beads close reasons, and a reconciliation script of equal effort that reads PR and CI state and detects a false done after the fact.

## Stop rule

- If the baseline catches every seeded F4 case in the pilot, record the result and stop H34.
