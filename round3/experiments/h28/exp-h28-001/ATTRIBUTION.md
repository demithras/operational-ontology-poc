# exp-h28-001 - INVALID (launch fault, orchestrator); does not count as an attempt

Run: candidate r3-g4-cand1 (7b9d7bc), seed 2821, 5,600 Byzantine cases + 1,000 honest controls per variant, launched through
scripts/run_h28.sh in a fresh worktree (HEAD == tag asserted) under caffeinate, 2026-10-10 16:32-16:57.
`verify_h28.sh`: evidence hashes ok, verdict reproduces.

## Verdict
Both variants INVALID with one reason each: "adapter catalogue is not frozen in FREEZE_G4 (non-dev id)".
ORACLE-AND-HARNESS-G4 s9 invalid_if: "adapters used are not the frozen catalogue (catalogue module sha256 != FREEZE_G4)".
The sha256 of src/r3_harness/h28/adapters.py was never added to protocol/FREEZE_G4.json after the harness build.

## Attribution: orchestrator (freeze step), not a variant and not the oracle
- The freeze entry is the orchestrator's duty after the harness build; it was omitted.
- Two gaps let it reach an official run: the launcher pre-flight (run_h28.py guard) did not check the catalogue entry, and the
  smoke run uses a dev id, for which the evaluator skips that check by design.
- Re-evaluating this evidence after adding the hash would freeze after seeing results; not done.

## Raw numbers (descriptive only, NOT a verdict)
| | Paladin | Conventional |
|---|---|---|
| forbidden classes (7) | all 0 | all 0 |
| target-mutation detection | 554/554 | 621/621 |
| mutants killed | 6/6 | 6/6 |
| outcome equality points | 24,613/24,613 | 24,613/24,613 |
| floors: crash / none-class / observer-fault | 467 / 1,600 / 622 | 467 / 1,600 / 622 |
| min per primitive / per (domain, system) | 599 / 800 | 599 / 800 |

## Author decision (2026-10-12)
exp-h28-001 does not count toward the 3-attempt budget (Q1). Erratum G4-E27 freezes the catalogue hash and the launcher refuses
a non-dev id without it (fix6). New candidate r3-g4-cand2, full suite + smoke, then the repeat exp-h28-001r on a NEW seed 2824
(corpus 2821 already seen). Seeds 2822/2823 stay reserved for attempts 2 and 3.

## Packing
Files over 2 MB are gzip-compressed (gzip -n -9); RAW_SHA256.txt holds the sha256 of every raw file as written by the run.
run.log = launcher output; launcher-steps.log = orchestration script steps.
