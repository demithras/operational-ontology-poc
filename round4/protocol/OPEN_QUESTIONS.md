# Open questions: author decisions needed before freeze

`scripts/freeze_protocol.py` refuses to freeze while any item below is unchecked. Seven items were decided in the 2026-10-28 interview; one new item from the access-grant follow-up is open.

- [x] **Test repositories.** Sandbox GitHub repositories (real branch protection, real check-runs, rate limits and account setup) or a local Gitea (no network dependency, but branch-protection behavior may differ from GitHub)? The baseline must use real GitHub controls to be fair, so Gitea needs an equivalence argument.
  Decision: two PUBLIC sandbox repositories on GitHub (real branch protection, required checks, CODEOWNERS). No Gitea. (author, 2026-10-28)
- [x] **Workers and adversaries.** Which agents act as workers (Claude Code sessions, which models) and which act as adversaries? Are the adversary and the worker the same model family? Fix credentials and call surface for each role.
  Decision: workers are Claude Code sessions on sonnet. The adversary is a deterministic fault injector for F1-F10 plus one opus agent with an adversarial prompt. (author, 2026-10-28)
- [x] **Real or synthetic projects.** Real IT projects (realistic items, real blockers, risk of real effects) or synthetic ones (safe, but a weaker oracle for realism)?
  Decision: synthetic (generated small repositories and work items; known oracle; no real effects). (author, 2026-10-28)
- [x] **Cost model for H36.** What counts as operator minute, agent token, setup effort and recurring maintenance; who logs them; what a fair equal-effort reconciliation script means in hours.
  Decision: operator minutes (manual log), agent tokens (from session transcripts), setup and maintenance hours (from git log). Separate frontier axes, never one combined score. (author, 2026-10-28)
- [x] **H35 time shift.** Does H35 need a time-shift replay (query effects after a retention gap) or is a same-session audit enough?
  Decision: a same-session audit is enough for the pilot. "Months later" is an explicit stated limitation, not tested. (author, 2026-10-28)
- [x] **Stale-lease bound.** The value of `H31.stale_lease_release_bound_seconds`, fixed before the baseline pilot and identical for both arms.
  Decision: 15 minutes (900 s), identical for both arms (`thresholds.H31.stale_lease_release_bound_seconds`). (author, 2026-10-28)
- [x] **Human spot-check rate.** The sampling rate of the human spot check in the H34 baseline.
  Decision: 10% of closed items (`thresholds.H34.baseline_spot_check_rate` = 0.10). (author, 2026-10-28)
- [ ] **Log store for the pilot (e.g. Loki or OpenSearch) and whether `revocation_bound_seconds` = 60 is right.** H37 needs one log store in Docker with a real ACL or role API, and a revocation bound (`thresholds.H37.revocation_bound_seconds`) identical for both arms. The freeze refuses until the author answers.
