# H35 — Provenance: why did this merge or deploy happen, answerable months later

## Claim

For any merge, deploy or closure, the question 'why did this happen' is answerable months later with all six K5 links (work item, agent, authority, policy version, evidence, observed outcome) resolvable without trusting the actor, and answerable more completely than from the GitHub audit log, the PR timeline and the bead history.

## Strong null

The GitHub audit log, the PR timeline and the bead history together answer 'why did this happen' as completely as a provenance record does; a separate provenance store adds nothing.

## Rivals

- The conventional stack already does this: PR timeline, audit log, bead close reasons and commit trailers link effect to item, actor and approval.
- The provenance record is complete only because the harness wrote it on a fast path; real months-old queries fail on retention, renamed repos or deleted branches.
- The links resolve, but to records the actor could rewrite, so the provenance is not trustworthy.
- Provenance quality depends on discipline (commit trailers, close reasons) that a well-run conventional team also has.

## Scope and limitation

The pilot uses a same-session audit (author decision 2026-10-28). Limitation, stated and not tested: "months later" retention (renamed repositories, deleted branches, expired logs) is not covered by this pilot.

## Mechanism under test

Each gated effect writes an append-only record binding work item, agent, grant, policy version, evidence digests and the observer's confirmation; the record sits in a store the acting agent cannot write to or alter.

## Primary falsifiers

- The conventional stack resolves all six links for every audited effect from sources the actor cannot rewrite.
- Any audited effect in the treatment has an unresolved link, or a link resolving to an actor-writable record.
- The treatment's completeness advantage disappears when the baseline adds an obvious plain control (commit trailers, close-reason convention, exported audit log).

## Experiment

Produce effects in both arms, then pose the same fixed set of 'why' questions about each effect to a question-answerer that may use only the arm's records; an independent grader resolves each of the six links against source-host and deploy ground truth.

1. Freeze the question set, the six-link rubric and the grader before any run.
2. Run the baseline arm first with all plain controls from baselines/FAIRNESS.md enabled (audit log export, PR timeline, bead history, commit trailers) and record completeness and time to answer.
3. The comparative thresholds are already fixed by the author (thresholds.json, comparative_basis); the baseline pilot only checks for headroom and does not change them.
4. Pilot one effect per arm; check that the treatment wrote provenance records (manipulation check) and that the control arm could not reach them through the file system.
5. Audit at least thresholds.H35.min_audited_effects effects per arm, in the same session as the effects (same-session audit; 'months later' is not tested).
6. For each link test whether the actor could rewrite the record it resolves to.

## Headroom rule

The comparative bar of this contract is read through `thresholds.headroom_rule`: the absolute bar applies while the baseline rate is at most 0.80; above it the treatment must close at least 50% of the baseline's misses, (treatment - baseline) / (1 - baseline); at a baseline of 0.95 or more the class is recorded as CEILING: no advantage measured, never REJECTED (verdict INCONCLUSIVE with reason "CEILING"). A fixed +20 bar is unreachable by construction above 0.80.

## Independent oracle

Independent grader that resolves each of the six K5 links from source-host API, deploy system and tracker ground truth, and checks writability of the cited record by the acting agent's credentials; it never accepts an arm's own summary of why.

## Fair baseline

GitHub audit log, PR timeline, bead history and close reasons, commit trailers and an equal-effort script that joins them into one answer.

## Stop rule

- If the baseline resolves all six links for every pilot effect from records the actor cannot rewrite, record the result and stop H35.
