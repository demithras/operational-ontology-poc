# Changelog

## 2026-10-28 - Author interview applied

- Recorded decisions 1-9 of the 2026-10-28 interview (sandbox repos, agents, synthetic projects, H34 forbid-vs-detect, H36 cost axes, fixed comparative thresholds, 900 s stale-lease bound, 10% spot check, H35 same-session audit).
- `thresholds.json`: all nulls replaced, all `_rule` keys removed, `comparative_basis` added; H34 gained `baseline_spot_check_rate` and `max_treatment_false_done_lifetime_seconds`.
- Removed the second freeze stage everywhere; `freeze_protocol.py` is single stage; `check_pack.py` fails on any null threshold.
- H34, H35, H36 contracts and READMEs updated; all open questions checked.

## 2026-10-28 — Round 4 draft 1

- Built from the upstream state at `4058fdd1ccbc94b4ae6286eeb5448f195a5b2aa7`.
- Changed the domain from manufacturing to coordination and control of AI agents across IT projects (author decision 2026-10-28).
- Added invariants C1-C3 and K1-K5, fault classes F1-F10, gated actions, hypotheses H31-H36, draft thresholds, baseline fairness contract, docs and pack checker.
- No Round 4 evidence exists. Nothing is frozen; `protocol/FREEZE.json` is intentionally absent.
