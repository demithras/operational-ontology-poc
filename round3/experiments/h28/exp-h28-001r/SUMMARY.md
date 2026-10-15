# exp-h28-001r - Gate 4 (H28) official result: Paladin SUPPORTED, Conventional SUPPORTED

Run: candidate r3-g4-cand2 (7da79e5), seed 2824 (G4-E27), 5,600 Byzantine cases + 1,000 honest controls per variant, launched
through scripts/run_h28.sh in a fresh worktree (HEAD == tag asserted) under caffeinate, 2026-10-12 15:58-16:29.
`minimum_overrides` is empty; `verify_h28.sh`: evidence hashes ok, verdict reproduces. Thresholds sha256 fa196766b3bc...

## Attempt history (Q1 budget: at most 3 official attempts per variant)
| id | candidate | seed | result | counts? |
|---|---|---|---|---|
| exp-h28-001 | r3-g4-cand1 | 2821 | INVALID both (catalogue not frozen; orchestrator launch fault, see its ATTRIBUTION.md) | no (author, G4-E27) |
| exp-h28-001r | r3-g4-cand2 | 2824 | SUPPORTED both | attempt 1 |
Pre-official checks on r3-g4-cand2: sharded suite 2149/2149; smoke exp-h28-smoke-dev-2 both SUPPORTED + verify; refusals exit 2
(no services; overrides on a non-dev id); live probe on 1e7419c: non-dev launch with an unfrozen catalogue refused, no evidence.

## Falsifier classes and floors (both variants identical where shown once)
| | Paladin | Conventional |
|---|---|---|
| effect_outside_scope / false_reconciled_success / governance_in_adapter | 0 / 0 / 0 | 0 / 0 / 0 |
| duplicate_effect / outcome_mismatch / progress_loss / envelope_mismatch | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| target-mutation detection | 574/574 | 640/640 |
| outcome equality at every reconcile point | 24,862/24,862 | 24,862/24,862 |
| honest progress checked | 4,667 (ratio 1.0) | 4,667 (ratio 1.0) |
| crash / none-class / observer-fault cases | 467 / 1,600 / 622 | same |
| min per primitive / per (domain, system) | 618 / 800 | same |
| honest controls (observed: manufacturing / project) | 1,000 (429 / 286) | same |
| twin pairs, R28-11a byte-exact differences | 5,600, 0 | 5,600, 0 |
| static governance-in-adapter audit hits / unresolved | 0 / 0 | 0 / 0 |
| observation independence: shared trust root | false | false |

## Mutation proof (frozen 1,200-case subset; each mutant must raise its target class)
| mutant | Paladin | Conventional |
|---|---|---|
| adapter_success_trusted | false_reconciled_success 813 | 813 |
| credential_scope_broadened | effect_outside_scope 342 | 347 |
| divergence_rewritten | false_reconciled_success 206, outcome_mismatch 305 | 206, 305 |
| idempotency_disabled | duplicate_effect 478 | 547 |
| observation_coupled | false_reconciled_success 695, outcome_mismatch 402 | 695, 408 |
| policy_gate_in_adapter | governance_in_adapter 324, progress_loss 117 | governance_in_adapter 324 |
Kill rate 6/6 for both.

## Dual-track comparison (descriptive, not part of the verdict)
- Security outcome: parity. Both variants hold every falsifier at 0 with identical floors; no measurable Paladin advantage.
- H28 code added since r3-g4-freeze (git diff --numstat, src only): Paladin +478/-30 (14 files, 35 lines mutant-only),
  Conventional +482/-12 (9 files, 13 lines mutant-only). Roughly equal size.
- Throughput (measured on exp-h28-001, identical variant code): Paladin about 16 case-record lines/s, Conventional about 40
  lines/s, i.e. Conventional about 2.5x faster. Per-request latency is not recorded by the H28 harness (p95 null).
- Paladin-specific value under the fair comparison: none measured at H28. The conventional implementation remains a viable path.

## Scope limits (as frozen)
L1 observer integrity trusted; L2 effects_only/none systems lower confidence, excluded from detection; L3 adapter attack code =
frozen catalogue; L4 logical ticks; L5 byte-exact payload digests; L6 project external effects only via the H28 overlay;
L7 legacy external_write path untouched.

## Packing
Files over 2 MB are gzip-compressed (gzip -n -9); RAW_SHA256.txt holds the sha256 of every raw file as written by the run.
