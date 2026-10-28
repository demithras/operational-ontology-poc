# Strong conventional baseline fairness contract

Every hypothesis is invalid if the baseline is a strawman. H36 compares against the **whole** conventional stack.

The conventional arm receives every control that plain beads and GitHub offer, configured with competent effort:

- beads: leases via `bd update --status=in_progress` plus an assignee, `bd ready`, and dependencies;
- GitHub branch protection on every default branch, including "include administrators" where available;
- CODEOWNERS for every path the agents can touch;
- required status checks, with "require branches to be up to date" so a green check is tied to the head SHA;
- required pull request reviews, with dismiss-stale-approvals on new commits;
- merge queue, if available on the repository plan;
- deploy environments with required reviewers;
- the audit log, with a regular export;
- a reconciliation script of equal effort to the treatment's equivalent component (same engineer-hours, same inputs, same heartbeat data);
- commit trailers and close-reason conventions that a well-run team would use.

## Same bar for both arms

- Same quality bar and the same engineering effort, logged in hours for both arms.
- Same agents (same models, prompts, credentials class) and the same seeded faults, in the same order.
- Same independent observers and graders; neither arm's own logs are ground truth.
- Shared low-level libraries are allowed when they remove implementation-quality confounds.
- Do not count treatment glue as free while counting equivalent baseline glue.
- Do not omit an obvious baseline control because it weakens the treatment advantage. If one is found late, add it before freeze, or invalidate and refreeze.

## Equivalence audit

Before each measurement an independent reviewer walks the list above against the live baseline configuration and records `fairness-audit.json`. Any control available in plain GitHub or beads that is missing is a `thresholds.common.max_baseline_controls_missing_vs_plain_github_beads` violation (limit 0) and the run is INVALID.

## Manipulation and leakage

- The treatment must be shown to be used (gate or lease calls per item above 0) before fan-out.
- The control arm's reach to treatment artifacts through the file system is checked before and reported after the run.
