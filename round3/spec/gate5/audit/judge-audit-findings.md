# G5 judge audit - findings (READ-ONLY, round3 @ d042f9a; matrix in matrix.md)

Excluded as already known and being fixed (G5-E34): commit-order replay, E33(c) RECONCILED_FAILED/in-doubt exemption, caveat
correlation index. Code lines refer to round3/src at d042f9a (main checkout, identical to d042f9a for src/ and spec/).

## 1. Blocking - flips a verdict on the committed evidence

B1 (M40) RC2 behavioural equality never compares the redelivery DECISION.
- Frozen text: PROT-H29 R29-11 (protections/PROT-H29.md:131-133) "redelivering every committed request_id returns the original
  decision with zero new world rows and zero new ledger rows. Any difference = recovery_divergence"; G5-E16 (gate5/OPEN-QUESTIONS.md:164-167)
  original decision = decision-plane status, and for non-OK its reason; G5-E12 (OPEN-QUESTIONS.md:152-153).
- Code: r3_harness/h29/judge_rec.py:99-105 checks only `marks_after == marks_before` and new ledger rows at t_redeliver. The
  rc2_redeliver replies are judged by judge_req._request as ordinary SAFE requests, where a DENIED reply has no class.
- Evidence (non-tamper, original reply OK + commit mark, RC2 redelivery answered DENIED):
  exp-h29-001r paladin 48 replies / 43 seqs (reason `authority`), conventional 48 / the same 43 seqs (`no_matching_allow` 33,
  `tool_not_available` 15); exp-h29-001 64 / 60 seqs each variant. Every one is an F6 sequence with a crash and a narrowing
  publish between the original OK and RC2 (example 001r env-000093: r001 OK t1, publish v4 t3 effective t6, kill/resume t7,
  rc2_redeliver r001 t33 -> paladin DENIED authority, conventional DENIED tool_not_available). Both variants re-decide a
  committed request under the new authority version instead of returning the original decision.
- With the text applied: recovery_divergence > 0 for BOTH variants in both runs -> REJECTED (reject_if, ORACLE-AND-HARNESS-G5.md:153),
  and the recovery equality ratio < 1.0.
- Required exemption to write down at the same time: F8 (ORACLE-AND-HARNESS-G5.md:89 "R27-5: non-OK with zero effect or exactly
  untampered behaviour"). Paladin answers UNAVAILABLE `idempotency_record_missing` to 932 RC2 and 699 in-sequence redeliveries in
  233 tamper sequences (each run); without the exemption the fix would flag them. Also extend the check to ordinary F4-dup
  redeliveries (ORACLE-AND-HARNESS-G5.md:84 "original decision repeated"); differing ordinary redeliveries outside tamper: 0.
- The redelivery check must also enter the recovery equality ratio (judge_rec.py counts only RC1 det/adm and RC2 view passes).

B2 (M49) outcome_progress_loss counts a loss only when the ORACLE outcome is RECONCILED_SUCCESS.
- Frozen text: PROT-H29 R29-12 (PROT-H29.md:141-143) "the outcome must also end RECONCILED_SUCCESS to count (otherwise
  outcome_progress_loss, same rule as PROT-H28 s8 progress_loss)"; PROT-H28.md:146-147 "final state must be
  RECONCILED_SUCCESS. Floor 1.0 (a deny-everything or never-dispatch variant cannot pass)".
- Code: r3_harness/h29/judge_fin.py:53 `if oc["oracle"][k][0] == "RECONCILED_SUCCESS" and oc["got"].get(k) != ...`. An intent
  not dispatched before its cap expiry gets oracle RECONCILED_FAILED (extoutcome rule F) from the ledger, so it is never a loss.
  aggregate.py:65 also restricts the floor to stratum env (ctrl excluded).
- Evidence (env, no kill, no Byzantine adapter, EXT:S and OBS up over [commit, E]): paladin 1603 requests in 888 sequences
  (001r) and 1617 in 878 (001) end RECONCILED_FAILED (variant == oracle); conventional 0. Official 001r paladin outcome =
  [5395 checked, 0 lost].
- With the text applied: s8 floor reading -> paladin outcome_progress_loss 1603 -> INCONCLUSIVE; "to count" numerator reading ->
  paladin overall 26781/28384 = 0.9435, F2 0.789, F7 0.900 (< 0.95) -> REJECTED. Conventional unchanged (all ratios 1.0).
- Corpus caveat (author ruling needed, do not fix the judge alone): Paladin dispatches only on dispatch_pending, which
  EQUIVALENCE-G4 F3 allows ("both may dispatch inline; the harness always calls dispatch_pending at the same points"); the H29
  generator places the first dispatch_pending after many windows close (001r env-000001: commits t1..t5, E = t9..t13, first
  dispatch t15). G4's schedule was request -> dispatch_pending -> advance (ORACLE-AND-HARNESS-G4.md:81). Fixing only the judge
  measures a generator artefact; fixing only the generator leaves a never-dispatch variant undetectable. Both need a ruling.

## 2. Blocking - ruling or gap before the next official run (no flip on current evidence)

B3 (M46) Scope of G5-E33(c) mark -> ledger. Text (OPEN-QUESTIONS.md:296-297) "evaluated at the end of every sequence (after
RC2 ...)"; code judge_wl.py:73-74 skips every sequence without RC2 and every tamper/state-loss sequence. In no-RC2 sequences each
variant has 139 committed intents with no row and no attempt (oracle RECONCILED_FAILED, exempt under E34b) and 2 with oracle
PENDING (001r env-004386 r008 ERP, env-005562 r008 NOTIFY; F3-byz, commit t8, end t18; 001: 3) - applying E33(c) to "every
sequence" would REJECT both variants on a Byzantine-adapter artefact. The E34(b) fix must state the scope (RC2 sequences only,
or exempt Byzantine adapters / non-terminal oracle states). Tamper sequences: 0 affected intents.

B4 (M12) Existence leak through non-OK reads is never checked. PROT-H29.md:81 "any field/link/existence beyond that view =
disclosure_leak"; PROT-H26.md:64 hidden objects answered exactly as absent. judge_req.py:141 compares only `status == "OK"`.
A DENIED/forbidden reply to a get on a hidden existing object (oracle INVALID not_found, disclosure_reads.py:16-19) passes.
Corpus exercises it: 1026 hidden-object reads per variant (001r), all INVALID not_found today.

B5 (M28) OK under UNRESOLVED-with-dependency exempted when committed. PROT-H29.md:100-102 has no such exemption;
judge_req.py:100 `(cls.kind == C.UNRESOLVED and cls.down and not committed)`. Under ANCHOR reply_lost the append is applied
server-side, so an OK ack without anchor confirmation also passes unanchored_ack: the anchor_skipped mutant shape under
reply_lost is unjudged. Corpus: 972 requests per variant under ANCHOR reply_lost (001r), none answered OK.

B6 (M29) approve / delegate / revoke are never classified (judge.py:186-194), though the frozen graph makes them governed
mutations -> {AUTH, ANCHOR} (PROT-H29.md:174-175, PROTOCOL-P1g.md:113-114). R29-7, spurious and unanchored_ack never run on them.
Corpus: 430 delegate + 430 revoke per variant inside F7 AUTH outages (001r; 414 in 001); replies UNAVAILABLE AUTH or INVALID
schema_invalid (admissible) - a DENIED would pass.

B7 (M65) invalid_if (a) "any armed CP never fired in its sequence" (ORACLE-AND-HARNESS-G5.md:155) cannot trigger:
judge_fin.py:120 `"fired": i >= len(missed) or True`. An unfired point only produces a harness row at resume (rc.py:36-40) ->
INCONCLUSIVE instead of INVALID. Related (M01): host deaths between calls (CP6) are recorded at the next resume (rc.py:42-44),
480-665 per variant per run, so the record cannot show when they fired.

B8 (M68) invalid_if (d) "service close() keys fail log verification" (ORACLE-AND-HARNESS-G5.md:158; :16-17 "root key
re-verification as in G4"): finalize.py:31-45 verifies anchor and AuthorityService only; integ["ext"] stays empty, no
ExternalWorld key/ledger verification.

## 3. Population sweep - where a plausible deviation would flip the outcome

| class / check | hits in 001 / 001r | evidence that a plausible DEVIATES would flip it |
|---|---|---|
| forbidden_effect | 001r 1 each (env-000192, E34a) | E34a only. |
| recovery_divergence | 001r pal 1, conv 9; 001 conv 13 (re-judge; 001 rows also carry world_log_unobserved, pre-E33) | E34a/E34b; B1 adds 43 (001r) / 60 (001) seqs to both variants. |
| disclosure_leak | 0 (E32 fixed the 001 hits) | B4: 1026 hidden reads per variant would flip if any reply status differed. |
| misclassified_dependency_failure | 0 | 001r per variant: 5515 BLOCKED-AUTH UNAVAILABLE AUTH, 2999 BLOCKED-AUTH input INVALID, 972 UNRESOLVED-ANCHOR UNAVAILABLE ANCHOR, 872 BLOCKED-ANCHOR UNAVAILABLE ANCHOR, 525 BLOCKED reads - all admissible; delegate/revoke 860 unjudged (B6). Never reached: AUTH+ANCHOR together (M23), crashed rid with dep down (M04), lease_gap / post-restart lease (M33), UNKNOWN replies while blocked (M24). |
| unanchored_ack | 0 | stream known in every sequence; no concurrent first-OK (M15); reply_lost OK path empty (B5). |
| stale_authority_commit / _after_restart | 0 | F6 stale-sensitive requests answered UNAVAILABLE AUTH (e.g. env-000093). |
| duplicate_commit / duplicate_effect | 0 | 0 rids with > 1 commit mark (M21 unreachable on this evidence). |
| false_success / false_reconciled_success | 0 | got == oracle at every counted point. |
| outcome_progress_loss (floor) | 0 | B2: paladin 1603 / 1617. |
| boundary_not_explicit | 0 | every B1 has an AUTH fault, every B3 an OBS window and reconcile calls (M58/M60 guards not needed on this evidence). |
| restricted_io | 0 | host-B auth refusals uncounted (M38); none expected. |
| RC2 view equality | 1.0 apart from E34 | 65 (001r) / 47 (001) sequences approve after an RC2, 1355/1365 reconcile after an RC2: end-state prediction (M39) produced no false diff because those approvals were consumed. |
| safe-progress ratios | 1.0 everywhere (001r) | B2 numerator reading lowers paladin; attacker exclusion (M48) affects only already-committed rid_replay requests (53/46). |
| mutation kills | 001r: nondeterministic_recovery and outbox_dropped_on_restart not killed (clean_count 1-2, E34 artefacts) | B1 lands in residue-5 (F6) subsets only; recovery-mutant subsets (residues 0,7 / 0,2) unaffected. |

## 4. Method
- Re-judged all four evidence sets in-process with the d042f9a judge (scripts/rejudge.py; services copied + gunzipped to work/);
  001r reproduces the official counts exactly (paladin forbidden_effect 1, recovery_divergence 1; conventional 1, 9; no harness rows).
- Raw/row sweeps: scripts/rawsweep.py, redeliver.py (redelivery status vs first decided status), rowsweep.py (per-request
  class x reply cross-tabs), outcap.py (oracle/got outcome per intent, attempts, alternative ratios), pend.py (no-RC2 PENDING).
  Outputs next to them: raw_*.json, rows_*.json, redeliver_sweep.json, outcap_*.json, lost_*.pkl, work/*.txt.
- No repository file written; no pytest; no git state change.

## 5. Notes (non-blocking; fix with the batch or record in SUMMARY)
M01 kill tick at resume; M04 crashed-rid UNRESOLVED drops `down`; M07 approvals from replies + lease-blind; M15 stream/concurrent/
approve anchoring gaps; M21 leftover marks; M23 AUTH removed from admissible down set; M24 UNKNOWN accepted for unknown-op probes;
M27 DENIED-with-dependency only checked off-SAFE; M30 exceptions while blocked unjudged; M38 host-B auth refusals; M39 RC2
prediction from end state; M48 attacker exclusion; M50 F1 window to last RC2, schedule-based class windows; M52 decision-plane-only
"unrelated"; M53 EXT:GEN-NULL absent from per-node floors; M66 invalid_if (b) manifest clause missing; M69 clean_count defaults to 0.
