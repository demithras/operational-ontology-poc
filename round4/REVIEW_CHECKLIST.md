# Author review checklist before Round 4 protocol freeze

- [ ] The upstream pin `4058fdd1...` in `protocol/UPSTREAM_EVIDENCE.json` is the intended evidence base.
- [ ] H11, H22 and H22w remain REJECTED and are not silently reopened under a new name.
- [ ] The invariants C1-C3 and K1-K5 match the intended meaning of coordination and control.
- [ ] The fault classes F1-F10 are strong enough; F10 is mapped to K1 and owned by H33 (see `hypotheses/h33/contract.json`).
- [ ] The gated actions and their independent observers (`model/actions.json`) are acceptable.
- [ ] Every contract names "the conventional stack already does this" as a rival.
- [ ] Every contract's `invalid_if` covers: oracle trusts self-report, strawman baseline, treatment not used.
- [ ] H33 states the risk of ending in parity like H11.
- [ ] H34 is recorded as the expected strongest hypothesis, with the reason.
- [ ] H36 is the only comparative-value claim; parity is REJECTED; a frontier is required.
- [ ] Every comparative threshold is null with a `_rule`; absolute-safety thresholds are acceptable.
- [ ] `baselines/FAIRNESS.md` lists every plain GitHub and beads control available.
- [ ] The pilot scope (2 repos, 2 agents, 1 gated action) and the stop rule are acceptable.
- [ ] Every item in `protocol/OPEN_QUESTIONS.md` is answered and checked.
- [ ] Only after review: `make check`, `make freeze`, commit `protocol/FREEZE.json`, then run the baseline pilot.
