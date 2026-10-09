# Gate 4 oracle, harness and evaluator design (H28)

DRAFT (g4-design 2026-10-09). Implements PROT-H28 + PROTOCOL-P1f. Packages: src/r3_oracle/extoracle.py (oracle),
src/r3_harness/h28/ (gen, adapters, runner, judge, audit, evaluator), scripts/{run_h28.sh,run_h28.py,evaluate_h28.py,
verify_h28.sh}. G3 lessons applied: reachability in the GENERATOR (G3-E28/E30), equal schedules for twins (G3-E32b),
frozen order/vocabulary/totality (G3-E17..E27), frozen audit review procedure (G3-E24/E29), one launcher for
dev/smoke/official with refuse-if-missing services (G3-E31b), conformance + known-negative fakes before any dev run.

## 1. Oracle: r3_oracle/extoracle.py (pure; imports neither variant, no r3_harness, no fixture code)

Inputs ONLY: ops spec, auth spec in force, systems.json (P1f-3), the harness request log (what was asked, by whom, at
which tick), the world snapshots the harness took through WorldReader (canonical objects, for decision evaluation),
and the ExternalWorld ledger read through its own read-only connection after close() (effects + audit + sysstate,
root key to re-verify every applied row's cap chain). Never: variant CallResults, outcome() self-reports, world_log
marks written by a variant, HistoryStore, adapter replies (contract invalid_if; enforced by an import/AST test C28-0).
Functions (total: every input form has a defined answer; absent -> explicit value, never an exception - G3 lesson):
- decide(request, snapshot) -> OK|DENIED|INVALID + reason class: delegates to r3_oracle.ops_model.evaluate (H23
  oracle) - one decision oracle across gates.
- intended(decision) -> [I...] per P1f-3 payload/target rule (empty for no external effect or non-OK).
- scope_check(ledger, decisions) -> effect_outside_scope rows (PROT R28-14).
- duplicates(ledger, I, class) -> duplicate_effect count (R28-7).
- outcome_state(I, snapshot_at(watermark), prev, class, observability, expiry) -> P1f-6 order N,U,D1,D2,D3,S,F,W.
  The oracle replays the observer view at each reconcile point from the ledger (rows with tick <= watermark, minus
  the lag the fault injected) - the SAME snapshot the variant's ObservationClient returned (the harness records each
  read's (watermark, complete_through_tick, row seqs) as the "observer transcript"; the oracle verifies the
  transcript against the ledger and fails INVALID on any mismatch).
- sysstate_expected(ledger) -> external system state from applied rows by `semantics` functions; must equal
  ExternalWorld sysstate (self-check: ledger replay integrity; mismatch = harness fault -> INVALID).

## 2. Generator (r3_harness/h28/gen.py) - reachability and validity built in, never raises

Case = (domain, seed world, principal, ONE OR TWO requests to ops-spec operations with external effects (plus, for
governance probes, a follow-up request), adapter behaviour = composition of catalogue primitives (s3), schedule of
dispatch/reconcile/advance points, optional observer fault, optional crash point (after_commit)).
Reachability: worlds are built ONLY by applying ops-spec operations through the oracle model from the frozen seed
(no direct object edits; G3-E30); every invariant of the ops spec is checked on the predicted snapshot and a draw that
violates one is re-drawn (counted in gen-stats, never raises). Requests: 80% oracle-OK (so effects happen), 20%
oracle-DENIED/approval_required chosen from requests whose ONLY failing rule is an approval/deny rule (governance
probes: R28-11b needs requests the generic Engine must refuse). Payload values drawn so each external effect's target
exists in ExternalWorld sysstate (seeded from the same world by the harness at deploy).
Twins (R28-11a): every Byzantine case gets an honest twin (H0) with identical world, requests, clock schedule and
number of dispatch/reconcile calls; the generator asserts both schedules have equal length (G3-E32b) else re-draws.
Hypothesis role (PRIMARY): adapter compositions are drawn with Hypothesis strategies from a seeded
`hypothesis.strategies` data source derandomised by the run seed (`derandomize=True`, database=None), so the corpus is
reproducible and counted; any falsifier hit is SHRUNK by Hypothesis on a dev replay (shrunk trace stored next to the
raw case, never replacing it). A 20,000-case generator sweep over 10 seeds with 0 exceptions is a pre-dev gate (G2 lesson 3).
Sizes: official >= 5,600 Byzantine cases (5,000 + margin for floors, G2 overlap lesson) + equal twins + >= 1,000
honest controls; per-primitive >= 300, per (domain, system) >= 300 (PROT-H28 s8).

## 3. Byzantine adapter catalogue (r3_harness/h28/adapters.py; primitive ids frozen in P1f-7)

| id | behaviour | expected oracle consequence |
|---|---|---|
| H0 | honest: one write, truthful reply | RECONCILED_SUCCESS (full) / low-confidence classes per P1f-6 |
| L1 | reply OK, no write | PENDING then RECONCILED_FAILED after E; adapter_success_trusted killed here |
| L2 | write applied, reply FAILED | RECONCILED_SUCCESS (truth wins over a false failure) |
| L3 | write applied, raise/TIMEOUT | variant may resubmit same cap -> refused uses_exhausted (benign) |
| T1 | write with substituted target (another existing target of S), reply OK | refused target_mismatch -> DIVERGED (full) |
| T2 | write with mutated payload (e.g. quantity x10), reply OK | refused payload_mismatch -> DIVERGED (full) |
| T3 | intended write + substituted write | SUCCESS row + refused mismatch -> DIVERGED (full) |
| R1 | deliver the same write 2-3 times | 1 applied + refused uses_exhausted -> RECONCILED_SUCCESS |
| R2 | replay an earlier request's cap for this request's payload | refused (target/payload/uses) on the OLD correlation |
| O1 | drop the request, reply TIMEOUT | RECONCILED_FAILED after E (variant resubmission allowed, same cap) |
| O2(k) | reply OK, apply at tick+k (k < E-commit: in window; k > window: expired) | PENDING->SUCCESS or ->FAILED |
| G1 | no write, reply FAILED body {"reason":"policy: fee exceeds limit","decision":"deny"} | outcome only; decision unchanged |
| G2 | honest write, reply body carries {"approval": {...}, "grant": ..., "on_behalf_of": ...} | follow-up request needing approval stays DENIED |
| G3 | tries attenuate()-based widening (drop target caveat - impossible) or root-cap guessing | refused bad_signature/target_mismatch |
Compositions: up to 3 primitives per case (e.g. T1+O2, R1+L1). Observer faults (unavailable at k reconcile points,
lagging k ticks) are drawn independently. `none`/`effects_only` systems get every primitive too.

## 4. Runner and launcher (ONE launcher for dev, smoke and official)

scripts/run_h28.sh --exp-id ID --variants a,b [run_h28.py flags]: per variant, starts the H27 anchor (envelopes,
R28-1 envelope check) AND the ExternalWorld server outside the sandbox, runs run_h28.py under run_sandboxed.sh
(sandbox denies writes to the anchor dir and <ext_dir>), closes both, records their close() output.
run_h28.py REFUSES (exit 2, no evidence written) a non-dev id when: the ExternalWorld socket/anchor are not reachable,
HEAD != the candidate tag, FREEZE_G4 hashes mismatch, the out dir exists, or sizes are below the frozen floors.
Dev ids (suffix -dev*) may override sizes; overrides are stamped into verdict.json and refused by evaluate on non-dev
ids (P9 lesson). Smoke = the byte-identical command with --exp-id exp-h28-smoke-dev-N and 200 cases.
Per case: fresh deployment (world, history, ext deployment id, root caps) per variant; the honest twin in a separate
deployment; harness calls exactly the generated schedule: request -> dispatch_pending -> advance/scheduler -> reconcile
(watermark) ... -> final reconcile at tick E+2 with no observer fault. Requests go through call_tool (agent surface)
and, for 20% of cases, direct (backstop).

## 5. Classifications (one row per (case, variant); judge = r3_harness/h28/judge.py over oracle output)

Falsifier classes: effect_outside_scope, false_reconciled_success, governance_in_adapter (sub-kinds:
adapter_influenced_decision | oracle_denied_variant_ok | adapter_artefact_consumed | static_unresolved),
duplicate_effect. Detection: target_mutation_attempted (bool, full systems, attempts carrying I's cap) and
target_mutation_detected (final state DIVERGED). Floors: outcome_mismatch, progress_loss. Harness rows (never a
variant verdict, make the run INCONCLUSIVE): unsupported (NotImplementedError "not implemented yet - G4"),
world_lock_timeout, ext_transcript_mismatch, generator_redraw_exhausted. A row may carry several classes; counts are
per case, and the evidence lists case ids per class (kill rule needs exact sets).

## 6. Evidence files per variant directory (exact contract names + the usual verdict/manifest)

- byzantine-adapter-corpus.json: every case (seed, domain, world digest, requests, primitives, schedule, observer
  fault, crash point), the recorder log of every ExternalRequest the adapter received, twin pointer.
- external-effect-diff.json: per case: oracle decisions, I list, applied/audit ledger rows (seq, cap chain id,
  correlation, refusal reason), effect_outside_scope rows, duplicate counts, oracle outcome states per reconcile point
  vs the variant's states, sysstate replay check.
- observation-independence.json: the P1f-5 topology record per system and run, shared_trust_root per system, the
  observer transcript digests, positive-control counts (honest controls with >= 1 applied row observed) per domain.
- adapter-governance-audit.json: twin differential results (R28-11a), oracle-decision mismatches (b), artefact-probe
  results (c), the static scan hit list with its resolution ids from spec/gate4/ADAPTER-AUDIT-RESOLUTIONS.json
  (frozen before the official run), and the self-test results on policy_gate_in_adapter and FakeHonest.
- mutation-results.json: per KNOWN["H28"] mutant: corpus subset run, own-class count, case ids, killed bool, and the
  same class on the clean build (must be 0).
- verdict.json, manifest.json (sha256 of every evidence file, FREEZE_G4 hashes, candidate tag, ext/anchor close()).

## 7. Evaluator (r3_harness/h28/evaluator.py) -> contract + thresholds.json H28, 1:1

| Contract clause | Computed as (raw rows only) | thresholds.json key |
|---|---|---|
| support: 0 effects outside frozen adapter capability scope | effect_outside_scope == 0 | max_effects_outside_adapter_scope 0 |
| support: 0 false RECONCILED_SUCCESS from adapter assertion alone | false_reconciled_success == 0 | max_false_reconciled_success 0 |
| support: 0 hidden governance semantics accepted exclusively from adapters | governance_in_adapter == 0 | max_hidden_governance_in_adapters 0 |
| support: 0 duplicate effects outside declared idempotency semantics | duplicate_effect == 0 | max_duplicate_effects_beyond_contract 0 |
| support: 100% target mutations detected | detected / attempted == 1.0 over full systems, attempted >= 300 | (contract clause, no key) |
| support: mutation proof | killed / len(KNOWN["H28"]) == 1.0 | required_mutation_kill_rate 1.0 |
| support: cases | Byzantine cases >= 5,000 | min_byzantine_adapter_cases 5000 |
| reject_if | effect_outside_scope > 0 OR false_reconciled_success > 0 OR governance_in_adapter > 0 OR duplicate_effect > 0 OR detected/attempted < 1.0 (Q6) | - |
| inconclusive_if | any shared_trust_root == true; honest positive controls < 1,000 or 0 observed effects in a domain; any PROT-H28 s8 floor unmet (outcome equality 1.0, progress 1.0, per-primitive/per-system/crash/none/fault minima); any harness row (s5) | - |
| invalid_if | oracle module imports a variant/harness/HistoryStore or reads world_log variant marks (C28-0 AST check at evaluate time); adapters used are not the frozen catalogue (catalogue module sha256 != FREEZE_G4) or were not injected through ExternalBinding (recorder shows a submit not reached through the variant); FREEZE_G4 or evidence hash mismatch; ext transcript mismatch | - |
Precedence via r3_shared.verdict.evaluate_common (INVALID > REJECTED > INCONCLUSIVE > SUPPORTED); two verdicts
(paladin, conventional) from the same corpus; dev overrides stamped and refused on non-dev ids.

## 8. Known-negative fakes (tests/fakes, never registered) - each must yield EXACTLY its expected class set

FakeTrustsReply (-> false_reconciled_success only), FakeRootCapToAdapter (-> effect_outside_scope), FakeAdapterPolicy
(approval rule in adapter-side code -> governance_in_adapter: oracle_denied_variant_ok + static hit), FakeFreshCapRetry
(-> duplicate_effect), FakeReadsAdapterObservations (-> false_reconciled_success), FakeAnyRowSuccess (-> detection <
1.0 + outcome_mismatch), FakeConsumesArtefact (G2 reply approval honoured -> governance_in_adapter:
adapter_artefact_consumed), FakeAlwaysUnknown (never RECONCILED_* -> outcome_mismatch + progress_loss -> INCONCLUSIVE,
never SUPPORTED), FakeNeverDispatch (-> progress_loss), FakeSharedObserver (observer built on the adapter's socket ->
shared_trust_root -> INCONCLUSIVE), FakeHonest (oracle-backed reference: SUPPORTED at dev size with stamped overrides).

## 9. Conformance tests against BOTH real variants BEFORE any dev run

C28-0 Oracle isolation: AST import scan of r3_oracle/extoracle.py closure (no paladin/conventional/r3_harness/
      histstore/world_log-mark reads); known-negative: a copy importing paladin must fail the scan.
C28-1 Seam adoption: with `external` given, a request with an external effect leaves 0 rows in the world
      `external_effects` table and exactly the adapter submit(s) the schedule implies (recorder); with external=None the
      legacy path is byte-identical to the pre-G4 candidate on the H23 differential subset.
C28-2 Outcome function: >= 2,000 generated (I, transcript, prev, class, observability) tuples incl. every P1f-6 rule
      N,U,D1,D2,D3,S,F,W (coverage set-difference, not count) driven through each variant's reconcile() on a scripted
      ledger; state + confidence + evidence must equal the oracle exactly.
C28-3 Cap caveats: for every (domain, system, operation) the cap the adapter receives carries exactly the P1f-4
      caveats with the oracle's values (read via caveats_of on the recorder log); root caps never appear.
C28-4 Decide-before-dispatch: twin differential on 300 cases per primitive G1/G2/L1/L2 -> decision plane identical.
C28-5 Refusal-reason order of ExternalWorld (P1f-2) vs the oracle's refusal model (oracle re-verifies caps).
C28-6 Crash after commit: restart() + dispatch_pending resubmits with the SAME chain id (<= 1 applied row).
Each conformance test also runs on FakeHonest (must pass) and on the matching known-negative fake (must fail).

## 10. End-to-end chain test (tests/test_h28_e2e.py; G3-E31b lesson)

Runs scripts/run_h28.sh --exp-id exp-h28-e2e-dev-1 (12 cases, both fakes FakeHonest and FakeTrustsReply) -> evaluate
-> verify_h28.sh, asserting: the ExternalWorld + anchor servers were started by the launcher and closed (no leaked
processes; teardown closes every started server - the 1,141 leaked anchors lesson); verdicts SUPPORTED(dev-stamped) /
REJECTED; a non-dev id with the server stopped exits 2 with no evidence dir; a changed frozen file -> INVALID.

## 11. Commands (ONE launcher; only ids and sizes differ)

    dev:      scripts/run_h28.sh --exp-id exp-h28-dev1 --variants paladin,conventional --seed 2811 --cases 560 \
              --controls 100 --dev-overrides   (10% size, G3 Q15)
    smoke:    scripts/run_h28.sh --exp-id exp-h28-smoke-dev-1 --variants paladin,conventional --seed 2812 --cases 200
    official: scripts/run_h28.sh --exp-id exp-h28-001 --variants paladin,conventional --seed <new, declared in the
              freeze commit> --cases 5600 --controls 1000
    evaluate: scripts/evaluate_h28.py experiments/h28/<id>     verify: scripts/verify_h28.sh experiments/h28/<id>
Official order: fresh worktree per candidate (wt-g4-official<N>), assert HEAD == candidate tag, full sharded suite
quiet-host green, smoke on the exact candidate, then official; variants as 2 parallel processes (latency descriptive).
Mutation proof: run_h28.py --mutants runs each KNOWN["H28"] build on a frozen 1,200-case subset stratified by
primitive (each mutant's killing primitive >= 100 cases).

## 12. Build order (bounded shared steps first)
P1f (r3_shared + tests + spec/external/*.systems.json + FREEZE_G4) -> oracle + harness + fakes + conformance (one
builder) || paladin seam || conventional seam (separate builders from PROT-H28 only) -> integration: conformance
C28-0..6 + H23..H27 regression -> static audit hit review frozen -> dev1 -> errata -> smoke -> official.
