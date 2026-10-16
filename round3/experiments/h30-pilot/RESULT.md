# H30 exploratory pilot - result (2026-10-16)

Status: EXPLORATORY (protocol/AUTHOR_DECISIONS_2026-10-16.md). No H30 verdict; AUTHOR_DECISIONS_2026-10-15 s4 (H30 NOT RUN) stands.

## Answer to Q0 (PREREG-step0.md)
Blast radius CAN differ between the variants, but only through three build-level defects, none of which follows from the
ontology-vs-conventional architecture. No architectural blast-radius difference was found by a static reading of round3 HEAD; the
14 BR-NEUTRAL cells were not verified by code check or test (see Limits), so this is a weak null, not a measurement. The author ruled the three to be bugs to
fix (AUTHOR_DECISIONS_2026-10-16 s5); they are fixed, so no candidate cell remains for step 1 and the pilot stops here.

| Id | Defect | Variant | Repro (red before fix) | Fix |
|---|---|---|---|---|
| M1 | Approval edge-issuer exclusion checked only when the approval is recorded, not when it is consumed: an approver who became an issuer on the Q..requester path afterwards still let the request commit (external effect reached RECONCILED_SUCCESS) | paladin | tests/test_pilot_m1.py | paladin/core.py `_approval_check` re-computes `excluded_approvers` at consume; paladin/ledger.py `claim_approval` now honours `verify` (it silently ignored it in both paths) |
| M2 | `subscribe`/`poll` built views from the cached policy without the G5 AUTH lease gate: a poll after a read grant was removed delivered the protected prop | conventional | tests/test_pilot_m2.py (with a no-publish control) | conventional/lowevents.py: both go through `_g5_pregate("read")` like the other low reads |
| M3 | Anchor completion rebuilt a missing anchor entry from the HistoryStore pending record, which an A6 attacker controls: replay then said VERIFIED for forged evidence | paladin | tests/test_pilot_m3.py | paladin/core_g2.py writes the pending record to a variant-private world-DB table `pal_pend` inside the commit's transaction; paladin/continuity.py completes anchors only from it (no world record -> left unresolved) |

Method validity: the step 0 analysis found the Gate 5 outbox-resubmission difference unprompted and classified it BR-neutral
(known-positive control, VERIFY-step0.md). Each fix has a revert proof (fix reverted -> its pilot test red; restored -> green).

## Regression check (full round3 suite, one pytest process per test file, 12 in parallel, JUnit name diff)
- Base (main content + red pilot tests) vs fixed: 2,624 test cases each; NEW failures 0; FIXED = the 3 pilot red cases plus
  `test_h29_e2e::test_serial_and_parallel_runs_give_byte_identical_evidence` (fails or passes independently of the fixes: timing-sensitive
  under 12-way parallel load); the remaining 41 failures are identical on both sides.
- Those 41 are an artefact of running from git worktrees: the e2e scripts call `<checkout>/round3/.venv/bin/python` by path and a
  worktree has no `.venv`. Re-run serially with the venv present, every affected file passes: h27_e2e 27, h28_e2e 9, h28_g4fix1 8,
  h28_g4fix4 8, h28_verdicts 8, h29_e2e 5, p1d_sandbox 4. `test_h27_e9_cases.py` holds helpers only (0 tests). The published
  Round 3 suite is not red.

## Limits
- Only the CANDIDATE cells were verified (VERIFY-step0.md checks M1-M3). The 14 BR-NEUTRAL cells of step0-report.md rest on the
  analyst's reading alone. Six are structural (no tamper primitive or no principal in the attacked component, or the attack is a
  read: A1/A2 prov, A5 obj/ext, A6 disc, A7 disc). Five are code-cited reasoning nobody re-checked (A3 ext, A3 prov, A5 prov,
  A7 obj, A7 prov). Three rest on H23-H27 gate parity and cap bounds, by the analyst's own note (step0-report.md s5): A3 obj,
  A6 obj, A6 ext.
- Scope: round3 HEAD only. The G6 revocation and containment code on the unmerged r3-paladin / r3-conv branches
  (step0-report.md s6) was not analysed, and containment cost (H30's COST metric, AUTHOR_DECISIONS_2026-10-15) was not asked.
- M2's window needs no governed call on the conventional service between the publish and the poll (the repro writes the world
  directly); the leak is real but narrow.
- M3 was reproduced with forged evidence only, not a forged authority `doc`; the fix removes the HistoryStore record as a source
  altogether, which covers both.
- H24 oracle coverage: `r3_oracle/approvals.py` judges an approval only against the requester's static delegation chain at approval
  time and does not model the PROT-H24 s3 edge-path issuer exclusion. H24's SUPPORTED verdicts (both variants) therefore never covered
  that rule; M1 was invisible to Gate 2. The verdict file is not changed by this pilot.
- The official Round 3 evidence was produced by the pre-fix code (tags r3-*); these fixes do not re-run any gate.

## Reading *(model)*
Under a fair comparison the remaining blast-radius differences were implementation defects in both directions (two in Paladin, one
in conventional). Nothing here points to an architectural security advantage for the ontology variant; the comparative question is
answered for blast radius only as far as a static reading of HEAD plus targeted repro of the candidate cells reaches: no
architectural difference found. That is too weak to rule out a Paladin advantage, above all in G6 containment, which was not read.
