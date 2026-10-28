# 06 Definition of done

## For the draft pack (this stage)

- [ ] `python scripts/check_pack.py` exits 0.
- [ ] H31-H36 contracts validate against `schemas/hypothesis-contract.schema.json`.
- [ ] Every invariant C1-C3 and K1-K5 and every fault class F1-F10 is covered by at least one contract.
- [ ] `protocol/thresholds.json` is `DRAFT_NOT_FROZEN`; every comparative threshold is null with a `_rule`.
- [ ] No `protocol/FREEZE.json` exists; the author freezes.
- [ ] The author has answered every item in `protocol/OPEN_QUESTIONS.md`.

## For the pilot

- [ ] Stage A freeze committed before any run.
- [ ] Baseline pilot run first; numbers recorded; comparative thresholds set from them; Stage B freeze committed.
- [ ] Manipulation check passed (treatment calls per item above 0, one item per arm).
- [ ] Control-arm file-system reach checked before and reported after.
- [ ] Fairness audit signed off: no control available in plain GitHub or beads is missing from the baseline.
- [ ] Every outcome judged by an independent observer, not by an agent's report.

## For the round

- [ ] Each of H31-H36 has a verdict: SUPPORTED, REJECTED, INCONCLUSIVE or INVALID, with the implementation status kept separately.
- [ ] Where both arms pass every gate, the result says "no advantage measured" and names the graded metric.
- [ ] H36 reports a cost and benefit frontier, not one score.
- [ ] A results file lists per hypothesis the evidence path, with parity and costs stated.
- [ ] Anything deferred has an owner and a trigger written in the results file.

A clean rejection or a stop after the pilot counts as done.
