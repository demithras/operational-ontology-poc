# exp-h29-001 attribution (orchestrator, 2026-10-13)

Run: candidate tag r3-g5-cand2 (327210b), seed 2921, full size (5,600 env + 600 ctrl + 200 bnd per variant), --mutants,
6 workers per variant, fresh worktree at the tag; evaluate_h29 exit 0, verify_h29 exit 0 ("evidence hashes ok",
"verdict reproduces"), tracked tree clean after the run. Official attempt 1 of 3 (seeds 2921/2922/2923 declared in FREEZE_G5).

Evaluator verdict (as computed, unchanged): paladin REJECTED, conventional REJECTED. The only reason for both:
"safety=2 ['disclosure_leak']". Every other support condition holds for both variants (overall safe progress 0.99996,
lowest slice 0.9979, recovery 1.0, misclassified 0, boundary B1-B4 50 each with 0 violations, mutation kill 7/7,
6,873 input-invalid probes in AUTH/ANCHOR windows, harness rows none).

## The four disclosure_leak hits (2 per variant, identical sequences)
| variant | sequence | read | value got = oracle | differs |
|---|---|---|---|---|
| paladin | env-004595 (F4+F5) | get Verdict:verdict-H-B-1 | INCONCLUSIVE = INCONCLUSIVE | reason text; derivation_hash (64 hex both) |
| paladin | ctrl-000355 | get Verdict:verdict-H-C-1 | SUPPORTED = SUPPORTED | reason text; derivation_hash (64 hex both) |
| conventional | env-004595 (F4+F5) | get Verdict:verdict-H-B-1 | INCONCLUSIVE = INCONCLUSIVE | reason text only (hash equal) |
| conventional | ctrl-000355 | get Verdict:verdict-H-C-1 | SUPPORTED = SUPPORTED | reason text only (hash equal) |

Every other prop (value, git_commit, ref) is equal to the oracle's low view. The differing props are exactly
ops_model.LOOSE_PROPS = {"Verdict": {"reason", "derivation_hash"}}, which the frozen model compares by FORM (reason
non-blank, derivation_hash 64 hex) because the prose fixes their inputs but not their exact text (G5-E27; the same rule
the H23-H28 world comparisons and recoverymodel.world_digest apply). Both reasons are non-blank and both hashes are 64 hex.

## Cause (harness)
src/r3_harness/h29/judge_req.py:_read (line 131) tests `(exp[0], exp[1]) != ("OK", body)`: a raw equality of the whole
reply body against the oracle's low-view object, with no LOOSE_PROPS normalisation. The same defect was found and fixed
for recoverymodel.world_digest in G5 fix1 (G5-E27) but not in the read judge. Reads of Verdict objects are rare (4 in
12,800 sequences; none in the dev/smoke runs). No read in this run disclosed an object or field outside the
principal's low view.

## Status
The verdict above is the evaluator's output and is not altered here. Whether this run is harness-INVALID (does not count
as an attempt) and is repeated on a new seed is an author decision (G4-E27 precedent).
