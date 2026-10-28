# Author review checklist before Round 4 protocol freeze

- [ ] The upstream pin `4058fdd1...` in `protocol/UPSTREAM_EVIDENCE.json` is the intended evidence base.
- [ ] H11, H22 and H22w remain REJECTED and are not silently reopened under a new name.
- [ ] The invariants C1-C3 and K1-K8 match the intended meaning of coordination and control.
- [ ] The fault classes F1-F15 are strong enough; F10 is mapped to K1 and owned by H33 (see `hypotheses/h33/contract.json`).
- [ ] H37 (agent access grants, K6-K8, F11-F15) is a separate hypothesis from H33; its observer reads the target system's real permission state, not the grant record; "access revoked" means new connections fail AND open sessions are terminated within 60 s, on Postgres and OpenSearch (security plugin).
- [ ] The headroom rule (`thresholds.headroom_rule`: 0.80 / 50% gap closure / 0.95 CEILING) is acceptable for every comparative bar.
- [ ] The gated actions and their independent observers (`model/actions.json`) are acceptable.
- [ ] Every contract names "the conventional stack already does this" as a rival.
- [ ] Every contract's `invalid_if` covers: oracle trusts self-report, strawman baseline, treatment not used.
- [ ] H33 states the risk of ending in parity like H11.
- [ ] H34 is recorded as the expected strongest hypothesis, with the reason.
- [ ] H36 is the only comparative-value claim; parity is REJECTED; a frontier is required.
- [ ] Every threshold has a fixed value (comparative ones are the author's minimum material effect, not derived from the baseline pilot).
- [ ] `baselines/FAIRNESS.md` lists every plain GitHub and beads control available.
- [ ] The pilot scope (2 repos, 2 agents, 2 gated actions: merge_pr and grant_access) and the stop rule are acceptable.
- [ ] The adaptive fault count (`thresholds.fault_sampling`: 20 initial, batches of 20, at least 10 baseline misses, cap 200, CEILING below the minimum at the cap) is acceptable.
- [ ] Every item in `protocol/OPEN_QUESTIONS.md` is answered and checked.
- [ ] Only after review: `make check`, `make freeze`, commit `protocol/FREEZE.json`, then run the baseline pilot.
