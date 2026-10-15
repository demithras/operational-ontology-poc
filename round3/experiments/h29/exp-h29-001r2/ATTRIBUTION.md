# exp-h29-001r2 attribution (orchestrator, 2026-10-15)

Run: candidate tag r3-g5-cand5 (3ceeaa5), NEW seed 2925 (author decision G5-E34), full size, --mutants, 6 workers, fresh worktree at
the tag; evaluate_h29 exit 0; verify_h29 exit 0 ("evidence hashes ok", "verdict reproduces"); tracked tree clean.

Evaluator verdict (as computed, unchanged): paladin INVALID, conventional INVALID. Sole reason for each:
"invalid_if (a): armed crash point crash:CP6_idle never fired in N sequence(s)" (paladin N=1: env-002127; conventional N=2: env-001064,
env-001087). Every safety/recovery/misclassification class is 0 for both variants and there are no harness rows.

## Cause (harness recording; DIAGNOSIS.md by a separate read-only agent)
CP6_idle is a crash point in the SHARED host (host.py ~158-166, PROTOCOL-P1g P1g-6): after the reply to the armed request, with
nothing in flight, the host SIGKILLs itself; variant code does not decide whether it fires. In all three sequences the death happened
(each record has a kills entry {kill: T, resume: T}, not forced) but no host_dead event was written: deaths noticed at a tick boundary
are recorded as events (driver.py ~194-195, the G5-E35 B7/M01 fix), while a death first noticed at a tamper step, a resume or a
no_host call is appended to kills without an event (rc.py ~18-23, ~42-43; driver.py ~83-84). The "fired" flag (judge_fin.py ~127-131)
reads events only, so these three fired crashes were counted as never fired. Population: the records with kills but no host_dead
event are exactly these three (3 of 2,040 armed CP6 sequences); the smoke (seed 2912) and dev5 runs on the same code had 0.

For information only (not a verdict): the diagnosis re-evaluated a scratch copy with those three sequences dropped; both variants
then come out SUPPORTED with no other reason.

## Status
The verdict above is the evaluator's output and is not altered. invalid_if (a) makes the run INVALID; how it is followed up (repeat,
seed, candidate) is an author decision.
