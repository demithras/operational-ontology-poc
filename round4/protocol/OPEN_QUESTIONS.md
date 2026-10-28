# Open questions: author decisions needed before freeze

`scripts/freeze_protocol.py` refuses to freeze while any item below is unchecked. Check an item only after writing the decision under it.

- [ ] **Test repositories.** Sandbox GitHub repositories (real branch protection, real check-runs, rate limits and account setup) or a local Gitea (no network dependency, but branch-protection behavior may differ from GitHub)? The baseline must use real GitHub controls to be fair, so Gitea needs an equivalence argument.
- [ ] **Workers and adversaries.** Which agents act as workers (Claude Code sessions, which models) and which act as adversaries? Are the adversary and the worker the same model family? Fix credentials and call surface for each role.
- [ ] **Real or synthetic projects.** Real IT projects (realistic items, real blockers, risk of real effects) or synthetic ones (safe, but a weaker oracle for realism)?
- [ ] **Cost model for H36.** What counts as operator minute, agent token, setup effort and recurring maintenance; who logs them; what a fair equal-effort reconciliation script means in hours.
- [ ] **H35 time shift.** Does H35 need a time-shift replay (query effects after a retention gap) or is a same-session audit enough?
- [ ] **Stale-lease bound.** The value of `H31.stale_lease_release_bound_seconds`, fixed before the baseline pilot and identical for both arms.
- [ ] **Human spot-check rate.** The sampling rate of the human spot check in the H34 baseline.
