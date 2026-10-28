# Changelog

## 2026-10-28 - Adaptive seeded-fault count

- Recorded the follow-up decision: 20 per class was the orchestrator's number, not the author's. New rule `thresholds.fault_sampling`: start at 20, add pre-registered batches of 20 until the baseline has missed at least 10 of the class, cap 200, CEILING below the minimum at the cap.
- H31-H34 and H37 contracts and READMEs reference `thresholds.fault_sampling`; `min_seeded_faults_per_class` is the initial count only.
- `check_pack.py` requires `fault_sampling` with the exact values and has a negative control.

## 2026-10-28 - Access grants (H37) and headroom rule

- Recorded the follow-up author decisions (agents-only access grants, new H37, `grant_access` as the second pilot action, headroom rule).
- Added invariants K6-K8, fault classes F11-F14, actions `grant_access` and `revoke_access`, hypothesis H37, `thresholds.H37` and `thresholds.headroom_rule`.
- H31, H32, H34, H35 contracts read their advantage bar through the headroom rule; a CEILING class is INCONCLUSIVE with reason "CEILING", never REJECTED. H36 now judges 6 classes (H31-H35 and H37).
- New open question (log store and revocation bound) blocks the freeze. Removed the stale `protocol/FREEZE.json`: thresholds changed, so it no longer matched the pack.
- `check_pack.py` covers H31-H37, C1-C3, K1-K8, F1-F14 and requires `headroom_rule`.

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
