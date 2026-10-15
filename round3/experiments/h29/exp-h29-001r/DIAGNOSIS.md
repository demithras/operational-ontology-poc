# exp-h29-001r findings diagnosis (g5-001r-diag)
Candidate: wt-g5-official2/round3 @ 80a3e6d (r3-g5-cand4). Read-only. In progress.

## F1 env-000192 (both variants) -> (B) judge/oracle defect: marks replayed in transcript order, not commit order

Sequence (seq_def, identical for both): crash armed CP1_before_commit key c001 (t0); c001 preregister_hypothesis H-A sent t=1 ->
host killed (events n=2 host_dead, n=3 c001 err=no_reply); resume at t=2, RC1 view_a == view_b, `committed: []` (rc1 marks []).
r002 edit_threshold T-A {max:5} at t=4 -> OK (RECONCILED_SUCCESS), commit mark world_seq 95 tick 4.
r003 notify_reviewer t=5 -> mark 96. c001 redelivered t=5 -> OK, commit mark world_seq 98 tick 5 (fresh commit, the CP1 kill left none).
RC2 at t=16: redeliveries c001/r002/r003 all `replayed: true`, original statuses; r004 at t=17 -> mark 99.
Both variants: identical marks (95,96,98,99), identical replies, identical world digest 136763fecd155d66.

Frozen texts: PROTOCOL-P1g s P1g-3 l.80 (CP1 = immediately BEFORE COMMIT of the transaction carrying the commit mark) and l.182
("CP1 leaves no committed row"). ops spec project.json edit_threshold rule `threshold-immutable-after-preregistration`: deny when any
governing hypothesis is not DRAFT (a decision-time rule). Seed: H-A phase DRAFT, T-A {min:10}. ORACLE-AND-HARNESS-G5 s1 l.29-31:
predict_world applies "the oracle decisions of committed requests IN COMMIT ORDER (committed = SAFE OK requests + UNRESOLVED requests
whose commit mark exists)".

Actual world: at world_seq 95 (tick 4) H-A was DRAFT (c001 uncommitted), so the edit was legal; H-A preregistered later at seq 98.
The invariant is NOT violated in the actual world. Object diff predicted vs actual: only Threshold:T-A (pred {min:10}, act {max:5});
links equal.

Mechanism (file:line, candidate 80a3e6d): judge.py:184-192 walks events in transcript order and judge_req.py:72 calls
process_marks(e) on the FIRST event of a rid; judge.py:161-181 then consumes ALL of that rid's marks regardless of world_seq. So the
crashed c001 event (n=3, t=1) consumed mark 98 (tick 5) and committed H-A PREREGISTERED into the Replayer before r002's mark 95 was
decided -> r002 DENIED -> forbidden_effect, and r002 not applied -> world_divergence.
Reproduced in-process (diag-001r/f1.py: identical classes + the T-A diff). Commit-order replay (diag-001r/f1b.py, marks sorted by
world_seq, decision at mark tick): r002 OK, r003 OK, c001 OK, r004 OK; predicted digest 136763fecd155d66 == actual, both variants.
Verdict: (B). The oracle's restart model (CP1 => nothing committed) agrees with the world_log and RC1; the defect is the judge's
replay order, which contradicts ORACLE-AND-HARNESS-G5 s1 "in commit order". Not a variant defect, not shared code.

## F2 conventional committed_effect_missing x8 -> (B) judge_wl.py does not implement E33(c) as written (two defects)

Re-judge in-process of all 6400 x 2 (diag-001r/sweep.py, services copied to diag-001r/svc/) reproduces the official counts exactly:
paladin {forbidden_effect 1, recovery_divergence 1}, conventional {forbidden_effect 1, recovery_divergence 9}; 0 harness rows.

All 8 hits have the same shape (diag-001r/f2v_{conventional,paladin}.txt): a governed request with one external effect is committed
(OK reply, commit mark) at t=19..21 INSIDE an F5 drop window on that effect's system (EXT:MES 20-28 / 20-32, EXT:NOTIFY 19-31 / 20-28,
EXT:REGISTRY 20-28); the cap's not_after_tick = commit tick + WINDOW 8 (PROT-H28 l.128; caveat values 27/28/29) falls inside or at
the end of the outage. Conventional dispatched inline and was refused: ExternalWorld unverified rows `refused / unavailable` carrying
caveat correlation == <rid>#0 (e.g. env-000632 r008: unverified seq 530, 531 at t=20, not_after 28; env-002032 r008 1763/1765,
r010 1764; env-003392 r010 2886/2887; env-003896 r005 3305/3307, r009 3306; env-004352 r010 3696/3697, r011 3698). After heal the cap
had expired; conventional made no further attempt; its reconcile at RC end reports RECONCILED_FAILED = the oracle's state (rule F of
P1f-6: no applied row and complete_through_tick > E).
Paladin in the same sequences: one `unavailable` attempt during the outage (except env-004352 r011: none) and then re-dispatched the
EXPIRED cap after heal -> audit rows `refused / expired` (e.g. env-000632 r008 audit 596 t=29, 600 t=39); same RECONCILED_FAILED
reply; not flagged only because those audit rows carry the correlation.
Frozen texts: P1f-2 l.68 (ExternalWorld refuses tick > not_after_tick as `expired`); P1f-6 l.136 ("Audit rows that MATCH I and were
refused (uses_exhausted, expired) are benign"). So Paladin's post-expiry retry is harmless but not required; conventional's not
retrying is not forbidden; no frozen text requires a second cap (R28-8 chain_ids = 1 argues against minting one). G5-E12 "never
dispatching a committed intent = recovery_divergence" does not apply: conventional did dispatch (the refused rows prove it).

E33(c) text: committed effect in the ledger "OR a terminal RECONCILED_FAILED / in-doubt state the oracle admits (else
committed_effect_missing)". judge_wl.py:79-87:
 (1) never consults the oracle state for the exemption (`st` is only copied into the detail, l.85-87) -> a terminal
     RECONCILED_FAILED that the oracle itself computed is flagged. Contradicts E33(c).
 (2) its own "attempt" exemption (docstring l.13-14) builds the attempt index at l.76-78 from r["correlation"] or
     r["claim"]["correlation"]; ExternalWorld `unavailable` refusals are decided before authentication (P1g-3 l.92-93, G5-E4), so the
     unverified row has correlation "" and the correlation exists only in claim["caveats"] -> real attempts are invisible.
Either defect alone produces all 8 hits. Verdict: (B). Not a variant defect (both variants end in the oracle's terminal state; the
only difference is a benign futile retry); not shared code.

Population (both variants, every committed intent with no applied ledger row; diag-001r/sweep_{v}.jsonl):
- oracle RECONCILED_FAILED + RC2 present + no audit row: conventional 8 (exactly the 8 flagged, each with 1-2 caveat-correlated
  `unavailable` attempts), paladin 0 (all 519 such paladin intents have audit rows, i.e. post-expiry `expired` refusals).
- oracle RECONCILED_FAILED + no row and no attempt of any kind: 139 per variant (135 shared), all in sequences WITHOUT RC2
  (F3-byz adapter sequences, planned F3/F3+F5/F3+F7/F3+F4), NOTIFY 71-72, ERP 50, WMS 16, MES 1, REGISTRY 0-1; none flagged because
  judge_wl.py:73 returns when there is no rc2 event. E33 says "evaluated at the end of every sequence (after RC2 ...)"; for a
  sequence with no RC2 the text is ambiguous; the oracle admits RECONCILED_FAILED there anyway, so no hit is expected either way.
- Paladin has 4421 RECONCILED_FAILED intents with only `expired` refusals (9843 `expired` audit rows; conventional 10): Paladin
  dispatches only on harness dispatch steps, often after the 8-tick cap window, while conventional dispatches inline. No frozen class
  covers this (the oracle outcome is computed from the ledger, so outcome_progress never counts it); descriptive only, out of F2 scope.

F1 population (transcript-order vs commit-order): 86 sequences per variant have marks whose world_seq order differs from the
transcript order of their first event (diag-001r/inv_{v}.jsonl). A commit-order replay (diag-001r/invchk.py) gives predicted ==
actual world digest in all 86 for both variants; the only sequence whose verdict the order changes is env-000192. (6 approval
sequences show r007 approval_required in my simplified replay because it does not replay approve events; the official judge, which
does, finds them clean and the digest still matches.)

## F3 sanity sweep
- Class hits: paladin = env-000192 only; conventional = env-000192 + the 8 F2 hits (env-000632, -002032 x2, -003392, -003896 x2,
  -004352 x2). No other class in either variant. Harness rows: none in either variant (fault-sequences `harness` empty for all 6400,
  confirmed by the re-judge).
- Evaluator (official-g5-001r-eval.log): {"paladin_verdict": "REJECTED", "conventional_verdict": "REJECTED"};
  both: "safety=1 ['forbidden_effect'] recovery_ratio=1.0 low_ratios={} misclassified=0 boundary=0". No sample/validity reasons
  printed. The reject is driven by forbidden_effect=1 (F1) and recovery_divergence>0 (evaluator.py:164: F1 world_divergence in both,
  plus the 8 F2 hits in conventional). All of these trace to the two (B) judge defects above; with them corrected per the frozen
  texts, my in-process replays show no remaining class in either variant (not a full re-evaluation: mutation/progress floors untouched).
