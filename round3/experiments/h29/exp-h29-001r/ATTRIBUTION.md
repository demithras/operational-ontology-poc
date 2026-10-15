# exp-h29-001r attribution (orchestrator, 2026-10-14)

Run: repeat of exp-h29-001 (author decision G5-E32), candidate tag r3-g5-cand4 (80a3e6d), NEW seed 2924, full size (5,600 env +
600 ctrl + 200 bnd per variant), --mutants, 6 workers, fresh worktree at the tag; evaluate_h29 exit 0; verify_h29 exit 0
("evidence hashes ok", "verdict reproduces"); tracked tree clean after the run.

Evaluator verdict (as computed, unchanged): paladin REJECTED, conventional REJECTED.
- paladin:      forbidden_effect 1, recovery_divergence 1 (both env-000192).
- conventional: forbidden_effect 1, recovery_divergence 9 (env-000192, plus 8 committed_effect_missing in 7 F1+F5 sequences).
No harness rows; no other class hit in either variant. A read-only re-judge of all 6,400 sequences per variant reproduced these
counts exactly (DIAGNOSIS.md, by a separate diagnosis agent; scripts kept in the orchestrator scratchpad).

## Finding 1 - env-000192, both variants: judge defect (replay order)
CP1_before_commit armed on c001 (preregister H-A); host killed at t=1, c001 no reply, RC1 committed []. r002 (edit_threshold T-A)
answered OK at t=4, committed at world_seq 95 while H-A was still DRAFT, so the decision-time rule
threshold-immutable-after-preregistration was not violated. c001 committed later on redelivery (world_seq 98, t=5).
judge.py (process_marks during the transcript walk) replays commit marks in TRANSCRIPT order; the crashed c001 event consumed mark
98 before r002's mark 95, so the oracle state had H-A preregistered and called r002 DENIED. ORACLE-AND-HARNESS-G5 s1 requires
"applying the oracle decisions of committed requests in commit order". Replayed in commit order every mark is OK and the predicted
digest (136763fecd155d66) equals the actual digest of both variants; the only differing object was Threshold:T-A. The inversion
occurs in 86 sequences per variant; only env-000192 changes a verdict.

## Finding 2 - 8 x committed_effect_missing, conventional only: judge defect (G5-E33(c) not implemented as written)
All 8: request committed during an F5 drop of its external system; the cap expired (not_after = commit + 8) before heal;
conventional dispatched at once, was refused `unavailable`, did not retry after expiry and reported RECONCILED_FAILED = the
oracle's state. judge_wl.py (lines ~79-87) never applies G5-E33(c)'s exemption "a terminal RECONCILED_FAILED / in-doubt state the
oracle admits"; in addition its attempt index reads `correlation` / `claim.correlation`, while `unavailable` refusals carry the
correlation only in claim.caveats (P1g-3, G5-E4), so real attempts were invisible. Either defect alone yields all 8. Paladin was not
flagged only because it also retried with the expired cap (refused `expired`, benign per P1f-6).

## Descriptive comparison (no frozen class; reported, not judged)
Paladin ended 4,421 intents RECONCILED_FAILED with only `expired` refusals (9,843 rows) against conventional's 10: Paladin
dispatches only at harness dispatch steps, often after the 8-tick cap window, so far more committed external effects lapse.
This is a measured operational weakness of Paladin's outbox, outside every H29 reject class.

## Status
Verdict unaltered. AUTHOR DECISION (2026-10-14, G5-E34): exp-h29-001r is harness-INVALID and does not count as an attempt; both
judge defects are fixed, an independent rule-by-rule audit of the whole judge against the frozen texts and a diagnostic re-judge of
the exp-h29-001 and exp-h29-001r evidence (diagnostic only, never a verdict) precede a new candidate and a run on the NEW seed 2925.
