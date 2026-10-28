# H36 — Total value: coordination and control gains outweigh setup and maintenance cost

## Claim

Taken together, the gains measured by H31-H35 (coordination, control and external truth for agents working across several IT projects) outweigh the setup and recurring cost of the EOO governance pattern relative to the whole conventional stack (beads, branch protection, CODEOWNERS, required CI, reconciliation script), reported as a cost and benefit frontier.

## Strong null

Against the whole conventional stack at equal engineering effort, the EOO governance pattern gives no net advantage: at best parity on safety and coordination at higher setup and maintenance cost.

## Rivals

- The conventional stack already does this: its safety and coordination equal the treatment's, and it is cheaper to set up and keep running.
- H31-H35 gains are real but each can be extracted as a small script or setting on the conventional stack without the EOO pattern.
- The treatment wins only by denying more legitimate work or costing more operator minutes and agent tokens than the frozen limits allow.
- The pilot is too small (2 repos, 2 agents, 1 gated action) to say anything about total value.

## Mechanism under test

One executable contract jointly derives leases, the cross-repo dependency view, the control gate, observer-confirmed closure and provenance, so fewer inconsistent decisions are made across repos than when each control is configured separately.

## Primary falsifiers

- All H31-H35 outcomes are at parity or favor the baseline after the baseline receives every plain control.
- The treatment's gains require exceeding any frozen cost, operator-minute or token limit.
- Any forbidden-effect or safe-progress regression against the baseline in any class.
- Any advantage disappears when the baseline gets an obvious equivalent control.

## Experiment

Combine the H31-H35 pilot results with a recorded cost model (operator minutes, agent tokens, setup effort, maintenance) and present a frontier of safety and coordination benefit against cost, per class, without collapsing them into one score.

1. Freeze the cost model (what counts as setup, recurring maintenance, operator minute and token) before any run; the author decides it, see OPEN_QUESTIONS.md.
2. Record the baseline arm's costs and outcomes first and set the comparative thresholds from them.
3. Record the treatment's costs and outcomes with the same agents and the same seeded faults.
4. Run the equivalence audit: for every treatment gain, check whether an obvious plain GitHub or beads control would erase it, and add that control to the baseline if so (before freeze) or invalidate.
5. Report a per-class benefit and cost table and a frontier; where both arms pass every gate write 'no advantage measured', not parity or a win.

## Independent oracle

The independent observers and graders of H31-H35 for benefit, plus a frozen cost meter (operator minutes logged by the operator, tokens from the model provider's usage records, setup and maintenance effort in logged hours); no figure comes from an agent's own estimate.

## Fair baseline

The whole conventional stack at equal engineering effort: beads (leases via status and assignee, bd ready, dependencies), GitHub branch protection, CODEOWNERS, required status checks and reviews with dismiss-stale-approvals, merge queue if available, deploy environments with required reviewers, audit log and a reconciliation script of equal effort.

## Stop rule

- If H31-H35 are all at parity or ceiling with the baseline in the pilot, record 'no advantage measured' and stop the round at the pilot; do not run H36 on a larger scale to look for a win.
- If H31-H35 work but H36 rejects, retain any independently useful mechanism and drop the claim that the EOO governance pattern is justified over the conventional stack for agent-run IT work.
