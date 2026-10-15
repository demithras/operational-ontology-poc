# Round 3 results - H23-H29 (H30 not run)

A view over the committed evidence, not evidence itself. Authoritative files: `round3/experiments/hNN/<exp-id>/verdict.json`
(per-gate `SUMMARY.md` / `ATTRIBUTION.md` are cited below). Protocol freeze `67fdc80ad37f24c6c585c928d78fd60801e13fcb735c48183f1229522eb49294`
(`round3/protocol/FREEZE.json`, frozen_at 2026-10-06); gate freezes `round3/protocol/FREEZE_G2.json` ... `FREEZE_G6.json`; thresholds
`round3/protocol/thresholds.json`; dual-track rule `round3/protocol/DUAL_TRACK.json`; author decisions
`round3/protocol/AUTHOR_DECISIONS_2026-10-06.md`, `-10-07`, `-10-08`, `-10-09`, `-10-12`, `-10-15`. Branch `round3`.
Every experiment runs the identical frozen corpus and evaluator against both variants (Paladin = EOO control plane; conventional = typed
service/API baseline built in parallel, `round3/protocol/DUAL_TRACK.json`), so each row carries two verdicts.

## Final verdicts

| Hypothesis | Paladin | Conventional | Authoritative experiment | Tag |
|---|---|---|---|---|
| H23 compromised-agent effect containment | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h23/exp-h23-002` | `r3-h23-exp002` |
| H24 delegation, revocation, expiry under concurrency | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h24/exp-h24-001` | `r3-g2-exp001` |
| H25 constitutional governance | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h25/exp-h25-003` | `r3-g3-exp003` |
| H26 sovereignty / noninterference | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h26/exp-h26-003` | `r3-g3-exp003` |
| H27 decision provenance is tamper-evident | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h27/exp-h27-001` | `r3-g2-exp001` |
| H28 external-system adapters, reconciliation | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h28/exp-h28-001r` | `r3-g4-exp001r` |
| H29 degraded-mode survivability | **SUPPORTED** | **SUPPORTED** | `round3/experiments/h29/exp-h29-001r3` | `r3-g5-exp001r3` |
| H30 realistic-task value comparison | **NOT RUN** (no verdict) | **NOT RUN** (no verdict) | none: `round3/experiments/h30/NOT-RUN.md` | none |

H30: author decision 2026-10-15 s4 (`round3/protocol/AUTHOR_DECISIONS_2026-10-15.md`, `round3/experiments/h30/NOT-RUN.md`): Gate 6 stopped
before any H30 measurement; status NOT RUN, "not REJECTED, not SUPPORTED". Hypothesis names are shorthand from the per-gate SUMMARY titles
(`round3/experiments/h2*/exp-*/SUMMARY.md`); the frozen definitions are `round3/spec/protections/PROT-H2*.md`.

## Full experiment record (nothing deleted)

Dev and smoke runs (ids containing `-dev` / `-smoke`) are not official and are omitted, except where a SUMMARY cites them.
"Counts" is as stated in the cited ATTRIBUTION / SUMMARY.

| Hyp | Run | Candidate / seed | Paladin | Conventional | Why it is not the final one (source) |
|---|---|---|---|---|---|
| H23 | exp-h23-001 | r3-h23-candidate 01bc7ac / 2310 | REJECTED | REJECTED | forbidden=3, backstop_failures=1 in both, one cause: approval binding of `on_behalf_of` (oracle literal per P1b text vs the orchestrator's P2a rework brief "same request"); contradictory pre-run spec, orchestrator error; oracle unchanged, both variants tightened to the protocol text (`round3/experiments/h23/exp-h23-001/ATTRIBUTION.md`; author decision 2026-10-07 s1) |
| H23 | exp-h23-002 | r3-h23-candidate-2 37b636c / 4271 | SUPPORTED | SUPPORTED | FINAL (`round3/experiments/h23/exp-h23-002/SUMMARY.md`). Post-hoc note on both H23 runs: runner `ROUND3` path bug made the in-run oracle-independence scan vacuous; independent AST re-check of `r3_oracle` found 0 variant imports, verdicts stand (`.../VERIFICATION_NOTE.md`) |
| H24 | exp-h24-001 | r3-g2-candidate c7dc324 / 2401 | SUPPORTED | SUPPORTED | FINAL, single official run (`round3/experiments/h24/exp-h24-001/SUMMARY.md`) |
| H27 | exp-h27-001 | r3-g2-candidate c7dc324 / 2701 | SUPPORTED | SUPPORTED | FINAL, single official run (`round3/experiments/h27/exp-h27-001/SUMMARY.md`) |
| H25 | exp-h25-001 | r3-g3-candidate1 0841307 / 2510 | REJECTED | INCONCLUSIVE | Paladin: 15 procedural mismatches (own code: absent-target deny rules, blank freeze_hash; one cause also a text gap); both: harness generator never produced refusal class `already_judged` (coverage) (`round3/experiments/h25/exp-h25-001/ATTRIBUTION.md`) |
| H25 | exp-h25-002 | r3-g3-candidate2 9334a6e / 2520 | REJECTED | SUPPORTED | Paladin: 3 procedural mismatches (own code: non-total helper on an absent experiment; decision tick on re-evaluation, also a text gap) (`round3/experiments/h25/exp-h25-002/ATTRIBUTION.md`) |
| H25 | exp-h25-003 | r3-g3-candidate3 f4b101d / 2530 | SUPPORTED | SUPPORTED | FINAL, pre-registered as the last Gate 3 attempt (G3-E33) (`round3/experiments/h25/exp-h25-003/SUMMARY.md`) |
| H26 | exp-h26-001 | r3-g3-candidate1 0841307 / 2610 | REJECTED | REJECTED | ORCHESTRATOR LAUNCH FAULT (run without the history anchor: 14,080 over-redaction / 3,192 false provenance in both); one non-low-equivalent generated pair (both); Paladin KeyError on a hidden field (2 variant errors) (`round3/experiments/h26/exp-h26-001/ATTRIBUTION.md`) |
| H26 | exp-h26-002 | r3-g3-candidate2 9334a6e / 2620 | REJECTED | REJECTED | one generated pair with unequal world_log schedules, divergence 7 in both; harness generator fault (`round3/experiments/h26/exp-h26-002/ATTRIBUTION.md`) |
| H26 | exp-h26-003 | r3-g3-candidate3 f4b101d / 2630 | SUPPORTED | SUPPORTED | FINAL, pre-registered as the last Gate 3 attempt (G3-E33) (`round3/experiments/h26/exp-h26-003/SUMMARY.md`) |
| H28 | exp-h28-001 | r3-g4-cand1 7b9d7bc / 2821 | INVALID | INVALID | orchestrator launch fault: adapter catalogue hash never added to FREEZE_G4; does not count toward the 3-attempt budget; fixed by G4-E27 (`round3/experiments/h28/exp-h28-001/ATTRIBUTION.md`). Raw numbers there are "descriptive only, NOT a verdict" |
| H28 | exp-h28-001r | r3-g4-cand2 7da79e5 / 2824 | SUPPORTED | SUPPORTED | FINAL, attempt 1 of the 3-attempt budget (`round3/experiments/h28/exp-h28-001r/SUMMARY.md`) |
| H29 | exp-h29-001 | r3-g5-cand2 327210b / 2921 | REJECTED | REJECTED | evaluator verdict unaltered (disclosure_leak=2 each); cause harness (read judge compared Verdict loose props raw); author: harness-INVALID, does not count, G5-E32 (`round3/experiments/h29/exp-h29-001/ATTRIBUTION.md`) |
| H29 | exp-h29-001r | r3-g5-cand4 80a3e6d / 2924 | REJECTED | REJECTED | evaluator verdict unaltered (Paladin forbidden_effect 1, recovery_divergence 1; conventional forbidden_effect 1, recovery_divergence 9); two judge defects (transcript-order replay; G5-E33(c) exemption not implemented); author: harness-INVALID, does not count, independent judge audit ordered, G5-E34 (`round3/experiments/h29/exp-h29-001r/ATTRIBUTION.md`, `DIAGNOSIS.md`) |
| H29 | exp-h29-001r2 | r3-g5-cand5 3ceeaa5 / 2925 | INVALID | INVALID | invalid_if (a): crash:CP6_idle "never fired" (Paladin 1 sequence, conventional 2) - a recording gap in the shared harness (host death not written as `host_dead`); all safety/recovery classes 0; author: does not count, G5-E36 (`round3/experiments/h29/exp-h29-001r2/ATTRIBUTION.md`, `DIAGNOSIS.md`) |
| H29 | exp-h29-001r3 | r3-g5-cand6 74df761 / 2926 | SUPPORTED | SUPPORTED | FINAL, official, no author invalidation (`round3/experiments/h29/exp-h29-001r3/SUMMARY.md`) |

Gate 5 judge audit before cand5 (G5-E35): 70 frozen rules checked, 46 conform, 23 deviated, 1 path never reached; two real defects in
both variants (B1 redelivered request re-decided under narrowed authority; B2 Paladin lapsed effects) fixed before cand5
(`round3/experiments/h29/exp-h29-001r3/SUMMARY.md`, attempt-history bullets).

## Dual-track comparison per gate

Descriptive only: "the value verdict belongs to H30 alone; a gate where both variants pass is recorded as parity, not as Paladin value"
(`round3/protocol/DUAL_TRACK.json`, per_gate_verdicts.value_attribution). Figures are quoted from the cited files; LOC is the
`security_specific_loc` field (excluding unchanged vendored Round 2 code) in each `verdict.json` `comparative` block. p95 latencies are from
contended hosts and non-authoritative per each SUMMARY; no H23-H29 clause uses them.

| Gate | Both meet every frozen bar? (pass/fail ceiling; does not rank the variants) | Paladin-specific value (SUMMARY's own statement) | Descriptive cost figures (Paladin vs conventional) | Files |
|---|---|---|---|---|
| H23 (002) | Both at the ceiling: forbidden effects 0/0, identity expansions 0/0, backstop 1.0/1.0, crash and concurrency 0/0, safe progress 1.0/1.0, mutants 6/6 both, 0 of 96,481 calls differ between variants | "No Paladin value is attributable at this gate." | LOC 1,672 vs 1,370 (5,099 total Paladin); components 15 vs 12; p95 17.4 vs 1.3 ms | `round3/experiments/h23/exp-h23-002/SUMMARY.md`, `verdict.json` |
| H24 | Both at the ceiling: scope amplifications / stale-or-forbidden effects / cycle grants 0/0/0 both; linearizability violations 0; race outcomes 1,400/1,400 both; progress 151,900/151,900 vs 151,965/151,965; mutants 4/4 both | "No Paladin value is attributable at this gate." | LOC 2,759 vs 2,299 (6,186 total Paladin); components 15 vs 12; p95 49.1 vs 7.8 ms | `round3/experiments/h24/exp-h24-001/SUMMARY.md`, `verdict.json` |
| H25 (003) | Both at the ceiling: procedural equality 1.0/1.0; fabricated judgments / emergency violations / forbidden effects 0/0/0 both; domain-specific privilege branches 0/0; mutation kill 1.0/1.0 | "No Paladin-specific value is attributable at this hypothesis." Paladin "needed more attempts" (3 vs 2 to first SUPPORTED) | LOC 4,999 vs 3,443 (7,588 total Paladin); components 21 vs 12; p95 28.3 vs 2.4 ms | `round3/experiments/h25/exp-h25-003/SUMMARY.md`, `verdict.json` |
| H26 (003) | Both at the ceiling: divergence / existence leak / value exfiltration / provenance overdisclosure 0/0/0/0 both; false provenance and hidden capability 0/0; A/A controls 500, 0 divergent; mutants 6/6 both | "no Paladin-specific value is attributable" | LOC 4,999 vs 3,443; components 21 vs 12; p95 6.4 vs 4.4 ms. Declared scope: activity volume and outcome class of authorised writes are declassified | `round3/experiments/h26/exp-h26-003/SUMMARY.md`, `verdict.json` |
| H27 | Both at the ceiling: affected decisions detected 19,234/19,234 vs 19,231/19,231; tampered history accepted 0/0; false alarms 0/0; binding divergences 0/0; mutants 4/4 both; anchor E1-E5 all true | "No Paladin value is attributable at this gate." | LOC 2,759 vs 2,299; components 15 vs 12 (both `verdict.json`); p95 replay 6.0 vs 1.2 ms | `round3/experiments/h27/exp-h27-001/SUMMARY.md`, `verdict.json` |
| H28 (001r) | Both at the ceiling: every falsifier 0 in both; target-mutation detection 574/574 vs 640/640; outcome equality 24,862/24,862 both; mutants 6/6 both | "Paladin-specific value under the fair comparison: none measured at H28. The conventional implementation remains a viable path." | H28 code added since r3-g4-freeze: Paladin +478/-30 (14 files), conventional +482/-12 (9 files), "roughly equal size". Throughput (measured on exp-h28-001, identical variant code): about 16 vs about 40 case-record lines/s, conventional about 2.5x faster; p95 not recorded | `round3/experiments/h28/exp-h28-001r/SUMMARY.md` |
| H29 (001r3) | Both at the ceiling: all 15 falsifier classes 0 and every ratio 1.0 in both; mutants 7/7 both; boundary probes B1-B4 n=50 each, 0 violations | "no measured outcome advantage at this gate"; "Paladin carries 505 vs 574 security-specific lines (-12%)" | G5 security-specific LOC 505 (12 files) vs 574 (14 files), "roughly equal size"; wall-clock 8,700.5 s vs 8,509.9 s (0.74 vs 0.75 sequences/s, +2.2% Paladin); p95 not recorded. External effects: Paladin 2,019 expired refusals vs 10 (resubmissions after the cap window following EXT outages), never-applied intents equal (790 vs 790), "no outcome difference", "Refusal noise only"; Paladin ends 900 vs 659 applied intents in a non-final reported state, "descriptive, no frozen class" | `round3/experiments/h29/exp-h29-001r3/SUMMARY.md` |

## What the result says

1. H23-H29 are per-protection pass/fail gates. Both variants meet every frozen bar on the final runs (every forbidden class 0, ratios 1.0; `round3/experiments/h2*/exp-*/SUMMARY.md`). Both hit the ceiling almost everywhere, so these gates do not discriminate between the variants.
2. No Paladin-specific advantage was MEASURED at any gate (H28 SUMMARY: "none measured"; H29 SUMMARY: "no measured outcome advantage"). That is not evidence of equal security: the ceiling effect means the gates could not rank the variants.
3. Descriptive differences the SUMMARYs did measure (not verdicts): Paladin security-specific LOC higher in H23-H27 (e.g. 4,999 vs 3,443 in H25/H26), 505 vs 574 at H29; higher p95 latency in H23-H27 on contended hosts; 3 vs 2 attempts to a SUPPORTED verdict at H25; about 2.5x lower throughput at H28 (`.../h28/exp-h28-001r/SUMMARY.md`); Paladin's 2,019 vs 10 expired-effect refusals at H29, outside every H29 reject class (`.../h29/exp-h29-001r3/SUMMARY.md`, `.../h29/exp-h29-001r/ATTRIBUTION.md`).
4. Paladin rejections before the final runs were in part its own defects (H25-001/002, H26-001 KeyError: `.../h25/exp-h25-00{1,2}/ATTRIBUTION.md`, `.../h26/exp-h26-001/ATTRIBUTION.md`); other rejections or invalidations of either variant were orchestrator launch faults, harness/generator/judge defects, or a contradictory pre-run spec (H23-001, H26-001/002, H28-001, H29-001/001r/001r2).
5. Dual-track consequence: the conventional baseline is a viable product path on the evidence (it met every bar; `round3/protocol/DUAL_TRACK.json` rule, H28 SUMMARY). The evidence does not show Paladin is worse or better on security outcomes.
6. The round's stop rule ("stop only when both variants reject") was never triggered: no gate's authoritative result was REJECTED for both; both-REJECTED runs (H23-001, H26-001/002) were followed by a new candidate and SUPPORTED/SUPPORTED (final rows above).
7. H30 was not run. It is the only gate designed to compare the variants directly (blast radius, containment/recovery cost). Author decision 2026-10-15 s4: a synthetic task corpus "cannot convincingly overturn that under the H30 contract's own rival/falsifier about synthetic-only advantage, while costing ~1-2 days" (`round3/protocol/AUTHOR_DECISIONS_2026-10-15.md`). Status NOT RUN, no verdict; the comparative question is OPEN (`round3/experiments/h30/NOT-RUN.md`).

## Limitations

- Ceiling effect: H23-H29 are per-protection pass/fail gates and both variants reach the ceiling (ratios 1.0, falsifier counts 0) almost everywhere, so they cannot rank the variants. "No Paladin-specific advantage measured" is not "equally secure". The only gate designed to compare them directly (H30) was not run (`round3/protocol/AUTHOR_DECISIONS_2026-10-15.md` s4), so the comparative question is open.
- H29 judge audit: the verdicts hold "under the judge as implemented with these 14 open deviations; they are not certified against the full frozen text". Open deviations: M04, M07, M15, M21, M23, M24, M27, M30, M38, M39, M48, M50, M52, M66; several make the judge more lenient on narrow paths (M24, M27, M30, M66 as named in the SUMMARY). M33 (a lease still valid after an ENGINE restart) was never reached by either variant (`round3/experiments/h29/exp-h29-001r3/SUMMARY.md`; `round3/spec/gate5/audit/judge-audit-findings.md` s5 as cited there).
- H29 declared scope: L1 observer/ExternalWorld/anchor/AuthorityService integrity trusted; L2 WORLD never faulted; L3 logical ticks; L4 H25 governance excluded; L5 Byzantine adapters = frozen H28 catalogue; L6 crash = SIGKILL of one host; L7 legacy cooperative paths untouched; L8 world store the only variant-process file the oracle reads (condition (b) partial); B4 boundary probe not variant-discriminating (G5-E24); schema probes only on the direct surface. H29 p95 latency not recorded (logical ticks only) (`round3/experiments/h29/exp-h29-001r3/SUMMARY.md`).
- H28 declared scope: L1 observer integrity trusted; L2 effects_only/none systems excluded from detection; L3 adapter attack code = frozen catalogue; L4 logical ticks; L5 byte-exact payload digests; L6 project external effects only via the H28 overlay; L7 legacy external_write path untouched (`round3/experiments/h28/exp-h28-001r/SUMMARY.md`).
- H26 declared scope: activity volume (seq/tick counters) and the outcome class of authorised writes are declassified; no principal-verifiable redacted chain (PROT-H26 D1-D5, rulings Q7/Q8) (`round3/experiments/h26/exp-h26-003/SUMMARY.md`).
- H27 scope: bound evidence = resource inputs + `newest` terms; business rules are not replayed (author decision 2026-10-07 #2c) (`round3/experiments/h27/exp-h27-001/SUMMARY.md`).
- H24 scope: among overlapping revoke-vs-execute races the effect committed first in every case (paladin 82, conventional 83; revoke-first 0); the revoke-wins branch is covered only by sequential control cases; `explicit_reason_mismatch` is informational (`round3/experiments/h24/exp-h24-001/SUMMARY.md`).
- H23-H27 latencies were measured on contended hosts and are non-authoritative (`round3/experiments/h23/exp-h23-002/SUMMARY.md`, `h24`, `h25`, `h26`, `h27` SUMMARYs).
- H23 verification note: the runner's in-run oracle-independence check was vacuous for both H23 runs and `candidate_version` in the envelopes is the sha256 of empty input; re-checked independently, `git_commit` identifies the candidate (`round3/experiments/h23/exp-h23-00{1,2}/VERIFICATION_NOTE.md`).
- H29 evidence history: three prior official-numbered runs did not count (exp-h29-001, -001r, -001r2: harness-INVALID or INVALID by author decision G5-E32/E34/E36); the H29 verdict rests on the 4th, after fixes made with knowledge of earlier results. The H28 and H29 attempts followed the G4-E27 rule that a seen corpus (seed) is never reused.
- H30 (moot, not run): the task source was decided as public incident patterns, each task citing a real public source, authored by a separate task-author agent and sealed before variants see it (`round3/protocol/AUTHOR_DECISIONS_2026-10-15.md` s1); domain mix both domains by class, A2/A7 manufacturing-only as a declared scope limit (s3, G6-E3). The corpus was never sealed; the unfinished builder work stays on local branches, not merged and not reviewed (s4).
- Dual-track caveats: per-gate comparisons are descriptive and the value verdict was reserved for H30 (`round3/protocol/DUAL_TRACK.json`); at H29 the LOC metric mixes G5 protections with the B1/B2 fixes and shared-signature edits, "no per-hunk attribution was done" (`.../h29/exp-h29-001r3/SUMMARY.md`).
