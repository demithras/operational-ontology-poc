# 06 Definition of done

## For the draft pack (this stage)

- [ ] `python scripts/check_pack.py` exits 0.
- [ ] H31-H37 contracts validate against `schemas/hypothesis-contract.schema.json`.
- [ ] Every invariant C1-C3 and K1-K8 and every fault class F1-F15 is covered by at least one contract.
- [ ] `protocol/thresholds.json` is `DRAFT_NOT_FROZEN`; every threshold, comparative ones included, has a fixed non-null value (`comparative_basis` recorded).
- [ ] No `protocol/FREEZE.json` exists; the author freezes.
- [ ] `thresholds.headroom_rule` exists and every `*_advantage_over_baseline_pp` contract cites it.
- [ ] The author has answered every item in `protocol/OPEN_QUESTIONS.md`.

## For the pilot (stage 1: merge_pr, H31-H35)

- [ ] Protocol freeze committed before any run.
- [ ] Baseline pilot run as a headroom check; numbers recorded; thresholds not changed by them.
- [ ] Manipulation check passed (treatment calls per item above 0, one item per arm).
- [ ] Control-arm file-system reach checked before and reported after.
- [ ] Fairness audit signed off: no control available in plain GitHub or beads is missing from the baseline.
- [ ] Every outcome judged by an independent observer, not by an agent's report.

## For stage 2 (H37, only if at least 1 of H31-H35 SUPPORTED in stage 1)

- [ ] Trigger evaluated and recorded from the stage-1 verdicts; if not met, H37 is NOT RUN (trigger not met) and the access baseline was not built.
- [ ] If met: access baseline built with equal effort, fairness audit signed off, H37 verdict recorded, H36 re-reported over 6 classes.

## For the round

- [ ] Each of H31-H37 has a verdict: SUPPORTED, REJECTED, INCONCLUSIVE or INVALID (a CEILING class is INCONCLUSIVE with reason "CEILING"); H37 may instead be NOT RUN (trigger not met), with the implementation status kept separately.
- [ ] Where both arms pass every gate, the result says "no advantage measured" and names the graded metric.
- [ ] H36 reports a cost and benefit frontier, not one score.
- [ ] A results file lists per hypothesis the evidence path, with parity and costs stated.
- [ ] Anything deferred has an owner and a trigger written in the results file.

A clean rejection or a stop after the pilot counts as done.
