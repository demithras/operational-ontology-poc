# exp-h29-001r3 - Gate 5 (H29) official result: Paladin SUPPORTED, Conventional SUPPORTED

Run: candidate r3-g5-cand6 (74df761), seed 2926 (G5-E36), 6,400 sequences per variant, launched through the H29 runner in a fresh
worktree (HEAD == tag asserted) under caffeinate, on 2026-10-15 from 10:03:27 (local); wall-clock 8,700.5 s (Paladin) and 8,509.9 s (conventional), 6 workers each. `minimum_overrides` is none; `verify_h29`: "evidence hashes ok".
Thresholds sha256 9872f463249c51509cb184deb31eee09d3573168faf309e1fdeb68a7b49a589e; evaluator sha256 d389d9c2e285c3cebba022a61b11e312042f7c18b584c87399950d18aa3e9db0.

## Attempt history (at most 3 official attempts per variant)
| id | candidate | seed | result | counts? |
|---|---|---|---|---|
| exp-h29-001 | r3-g5-cand2 (327210b) | 2921 | evaluator REJECTED both (disclosure_leak=2 each: read judge compared Verdict loose props raw); author: harness-INVALID, G5-E32 (b37a2ba, 75f9ab7, fix ee59fa7) | no (author) |
| exp-h29-001r | r3-g5-cand4 (80a3e6d) | 2924 | evaluator REJECTED both (transcript-order replay; G5-E33(c) exemption missing); author: harness-INVALID, judge audit ordered, G5-E34 (d042f9a, fix d67026a) | no (author) |
| exp-h29-001r2 | r3-g5-cand5 (3ceeaa5) | 2925 | INVALID both by invalid_if (a): crash:CP6_idle "never fired" (paladin 1 sequence, conventional 2) - a recording gap, G5-E36 (7b0e8dc, 4d9eefa, fix 5cc9a03) | no (author) |
| exp-h29-001r3 | r3-g5-cand6 (74df761) | 2926 | SUPPORTED / SUPPORTED | yes (official, no author invalidation) |

- exp-h29-001r2 cause: CP6_idle is a crash point in the shared host (host.py ~158-166); in 3 of 2,040 armed CP6 sequences the host died but a death noticed at a tamper step, resume or no_host call was appended to `kills` without a `host_dead` event (rc.py ~18-23, ~42-43; driver.py ~83-84), and the "fired" flag (judge_fin.py ~127-131) reads events only. Every safety/recovery/misclassification class was 0 for both variants; a scratch re-evaluation without those three sequences gave SUPPORTED for both (information only, not a verdict). Fix: G5-E36, every host death recorded as host_dead (5cc9a03, merge 74df761).
- Judge audit (G5-E35, 803053c): 70 frozen rules checked: 46 conform, 23 deviated, 1 path never reached (spec/gate5/audit/judge-audit-matrix.md). Two were real defects in BOTH variants, author-owned: B1 a redelivered request was re-decided under narrowed authority instead of returning the recorded decision (paladin 2e5b04b, conventional 4c0108b); B2 Paladin lapsed effects (fixed by inline dispatch, 2e5b04b). B3-B8 were orchestrator/harness items (fix 3b4ff11). Both fixed before cand5 (re-frozen in 3ceeaa5).
- Judge audit, open items: of the 23 deviations, 8 were fixed before cand5 (B1-B8 = M40, M49, M46, M12, M28, M29, M65, M68) and one non-blocking note was fixed with them (M01, crash tick recorded at resume). 14 deviations remain OPEN and are NOT fixed in this candidate: M04, M07, M15, M21, M23, M24, M27, M30, M38, M39, M48, M50, M52, M66 (spec/gate5/audit/judge-audit-findings.md s5). The auditor judged them non-blocking because none changes a verdict on the committed evidence (population sweep, findings s3); several make the judge more lenient on narrow paths (e.g. M24 accepts UNKNOWN for unknown-operation probes; M27 checks DENIED-with-dependency only outside SAFE; M30 leaves exceptions while blocked unjudged; M66 the invalid_if (b) manifest clause is missing). One path is UNTESTED: M33 (a lease still valid after an ENGINE restart) was never reached by either variant. The H29 verdicts above hold under the judge as implemented with these 14 open deviations; they are not certified against the full frozen text.
- Other gate errata cited: G5-E31 the anchor head at reply is read from the anchor log file, an unreadable head is a harness row (3bf3c3e, fixes 7cbaee2 and 145d6a5); G5-E33 world_log commit marks cross-checked against anchor and ExternalWorld (6c9aca9, 62b616b).

## Falsifier classes and floors (both variants identical where shown once)
| | Paladin | Conventional |
|---|---|---|
| duplicate_commit / duplicate_effect / forbidden_effect | 0 / 0 / 0 | 0 / 0 / 0 |
| effect_outside_scope / false_reconciled_success / false_success | 0 / 0 / 0 | 0 / 0 / 0 |
| stale_authority_commit / stale_authority_after_restart | 0 / 0 | 0 / 0 |
| unanchored_ack / tampered_record_trusted / disclosure_leak | 0 / 0 / 0 | 0 / 0 / 0 |
| recovery_divergence / recovery_nondeterministic | 0 / 0 | 0 / 0 |
| misclassified_dependency_failure / boundary_not_explicit | 0 / 0 | 0 / 0 |
| safe_progress_ratio / recovery_ratio / lease_gap | 1.0 / 1.0 / 0 | 1.0 / 1.0 / 0 |
| per-class ratios F1-F8 | F1 1.0, F2 1.0, F3 1.0, F4 1.0, F5 1.0, F6 1.0, F7 1.0, F8 1.0 | F1 1.0, F2 1.0, F3 1.0, F4 1.0, F5 1.0, F6 1.0, F7 1.0, F8 1.0 |
| per-node ratios (ANCHOR, OBS, EXT:ERP/MES/NOTIFY/REGISTRY/WMS), post_recovery | ANCHOR 1.0, OBS 1.0, EXT:ERP 1.0, EXT:MES 1.0, EXT:NOTIFY 1.0, EXT:REGISTRY 1.0, EXT:WMS 1.0, post_recovery 1.0 | ANCHOR 1.0, OBS 1.0, EXT:ERP 1.0, EXT:MES 1.0, EXT:NOTIFY 1.0, EXT:REGISTRY 1.0, EXT:WMS 1.0, post_recovery 1.0 |
| requests during faults: ANCHOR (blocked / safe-to-run), AUTH (blocked / safe-to-run) | ANCHOR 1,800 / 910; AUTH 9,970 / 5,381 | ANCHOR 1,800 / 910; AUTH 9,970 / 5,381 |
| boundary probes B1 / B2 / B3 / B4 (n, violations) | 50, 0 / 50, 0 / 50, 0 / 50, 0 | 50, 0 / 50, 0 / 50, 0 / 50, 0 |
| input-invalid probes: total / in auth-anchor window / boundary total | 19,746 / 6,930 / 669; per shape total missing_input 3,165, unknown_key 2,380, unknown_operation 6,797, unknown_tool 4,025, wrong_type 3,379; boundary per shape missing_input 150, unknown_key 100, unknown_operation 169, unknown_tool 100, wrong_type 150; lease_gap 0 | 19,746 / 6,930 / 625; per shape total missing_input 3,165, unknown_key 2,380, unknown_operation 6,797, unknown_tool 4,025, wrong_type 3,379; boundary per shape missing_input 150, unknown_key 100, unknown_operation 125, unknown_tool 100, wrong_type 150; lease_gap 0 |
| harness rows | none (harness rows: 0) | none (harness rows: 0) |

(001r2 reference, for orientation only: all 15 classes 0, all ratios 1.0, boundary 50/50/50/50 with 0 violations, input-invalid probes total 19,739 for both, in-window 6,922, boundary_total 669 Paladin vs 625 conventional.)

## Mutation proof (each mutant must be killed)
| mutant | Paladin | Conventional |
|---|---|---|
| anchor_skipped_when_unavailable | killed | killed |
| dependency_failure_as_denial | killed | killed |
| fail_open_on_authority_outage | killed | killed |
| global_halt_on_fault | killed | killed |
| nondeterministic_recovery | killed | killed |
| outbox_dropped_on_restart | killed | killed |
| stale_cache_after_restart | killed | killed |
Kill rate 7/7 (rate 1.0) / 7/7 (rate 1.0) (001r2: 7/7 both).

## Dual-track comparison (descriptive, not part of the verdict)
- Security outcome: parity: every one of the 15 falsifier classes is 0 and every ratio (overall, F1-F8, per node, post_recovery, safe_progress, recovery) is 1.0 in both variants (001r2 pattern: parity, every falsifier 0, all ratios 1.0 in both variants).
- G5 security-specific code (`git diff -U0 r3-g4-exp001r..r3-g5-cand6 -- round3/src/<variant>`; metric = added lines that are non-blank
  and not starting with `#`; docstring lines are counted; new files count in full; deletions not subtracted):
  - Paladin: security_specific_loc = 505 (570 added raw, 44 deleted), security_specific_components = 12 files, of which 3 new G5 modules
    (continuity.py 197, leasing.py 45, depgraph.py 30 = 272 lines) and 9 changed files (233 lines): core.py 71, core_g2.py 50, deployment.py 42,
    extdispatch.py 23, ledger.py 15, histledger.py 13, boot.py 11, extoutbox.py 5, variant.py 3.
  - Conventional: security_specific_loc = 574 (670 added raw, 47 deleted), security_specific_components = 14 files, of which 3 new G5 modules
    (g5svc.py 270, g5deps.py 92, g5journal.py 32 = 394 lines) and 11 changed files (180 lines): service.py 59, provenance.py 49, lowreads.py 15,
    extout.py 12, variant.py 12, store.py 9, authority_ops.py 8, histledger.py 6, extrecon.py 3, extsvc.py 3, tools.py 4.
  - Roughly equal size (conventional +14% in lines). The same diff in round3/src outside the variants is shared harness/oracle/shared-service code (r3_harness/h29, r3_oracle, r3_shared; 77 files in all under round3/src including the two variants) and is not counted as variant security code.
  - Caveat: the change set mixes G5 protections with the B1/B2 fixes and shared-signature edits; no per-hunk attribution was done.
- p95 latency: not recorded. cases.jsonl.gz (checked on exp-h29-001r2) carries logical ticks only (L3), no per-call wall-clock timings, so p95_latency_ms stays null.
- Throughput: run wall-clock only, 6,400 sequences with 6 workers: Paladin 8,700.5 s (0.74 sequences/s), conventional 8,509.9 s (0.75 sequences/s), +2.2% for Paladin; this includes harness and mutant overhead and is not a per-call throughput measurement.
- Paladin-specific value under the fair comparison: no measured outcome advantage at this gate: both variants are SUPPORTED with identical safety, progress and recovery numbers; Paladin carries 505 vs 574 security-specific lines (-12%), and its outbox resubmits more after EXT outages (2,019 vs 10 expired refusals) with no outcome difference.
- External-effect difference (class table measured on exp-h29-001r2, seed 2925, cand5; totals re-measured on this run in the last row; unit = intent (case, rid, effect_index), window = commit tick .. commit+8 in both variants):

| class (001r2) | P intents | P lost | P expired rows | C intents | C lost | C expired rows |
|---|---|---|---|---|---|---|
| a healthy | 11184 | 138 | 18 | 11321 | 139 | 5 |
| b EXT fault | 2601 | 563 | 1961 | 2603 | 563 | 6 |
| c ENGINE crash | 2514 | 0 | 0 | 2487 | 0 | 0 |
| d F4 | 6182 | 34 | 5 | 6205 | 34 | 0 |
| e other (OBS/AUTH/ANCHOR) | 4479 | 77 | 22 | 4578 | 77 | 1 |
| ALL | 26960 | 812 | 2006 | 27194 | 813 | 12 |
| 001r3 ALL | 26881 | 790 | 2019 | 27113 | 790 | 10 |

  001r3 never-applied intents are equal (790 vs 790); Paladin's 2019 expired refusals (vs 10) are resubmissions after the cap window following EXT outages; Paladin ends more applied intents in a non-final reported state (900 vs 659, mostly crash and F4 classes) - descriptive, no frozen class.

  Cause: after an EXT outage heals past commit+8, Paladin's outbox (extdispatch.py due()/dispatch) keeps resubmitting up to 3 times and the world
  refuses with "expired", while the conventional outbox (extout.py _eligible) skips intents past their expiry. No outcome difference: the lost
  sets are identical (811 intents lost in both on 001r2; 1 healthy intent applied in P but not C; 0 the other way), every lost intent ends
  non-SUCCESS in both, and the 2,006 expired rows add no lost effect conventional does not also lose (625 rows retry already-applied intents,
  1,381 rows are only attempts on intents conventional never submits). Refusal noise only.

## Scope limits (as frozen)
L1 observer/ExternalWorld/anchor/AuthorityService integrity trusted; L2 WORLD never faulted (loss = B4); L3 logical ticks; L4 H25 governance
excluded; L5 Byzantine adapters = frozen H28 catalogue; L6 crash = SIGKILL of one host; L7 legacy cooperative paths untouched.
Added at Gate 5:
- L8 the world store is the only variant-process file the oracle reads (G5-E33 cross-checks the world_log commit marks against the anchor and
  ExternalWorld); condition (b) is partial: anchor entries do not record OK vs DENIED.
- The B4 boundary probe is explicit by shared host construction and is NOT variant-discriminating (G5-E24).
- Schema (input-invalid) probes run only on the direct surface (L5 of G5-E29).

## Verdict
Paladin SUPPORTED; Conventional SUPPORTED. Reasons: none (reasons list empty for both variants). Mutants 7/7 killed in both variants; boundary B1-B4 n=50 each, 0 violations in both variants;
probes input-invalid probes 19,746 total in both variants, 6,930 in the auth-anchor window, lease_gap 0; boundary_total 669 (Paladin) vs 625 (conventional); no misclassification; payload sha256 f7c9b1bf69c02bfde2855b47b25bdfee3d299d96f5a69aa3a5270dbffa29225c / 35755abf58e30aee1f094373c354072d34cb4689f0ec0ee9d61992fe01a9ff12.
H29 is SUPPORTED for both variants on the same candidate and seed: the dual-track comparison is a parity result on the frozen thresholds.

## Packing
Files over 2 MB are gzip-compressed (gzip -n -9); RAW_SHA256.txt holds the sha256 of every raw file as written by the run.
