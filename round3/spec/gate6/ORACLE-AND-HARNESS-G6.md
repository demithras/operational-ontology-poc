# Gate 6 oracle, harness, measurement and evaluator design (H30)

DRAFT (g6-design 2026-10-15, round3 HEAD 3588afe). Implements PROT-H30 + TASK-CORPUS-SPEC. Packages: src/r3_shared/opplane.py
(+ identity revocation, ExternalWorld cap revocation/route quarantine: P1h), src/r3_oracle/incident.py (taint set, minimal
containment state, BR set), src/r3_harness/h30/ (rules, overlay_gen, validate, taskplay, ladder, probe, judge, latency, machinery,
evaluator, mutation, evidence_out, finalize, launch), scripts/{run_h30.sh, run_h30.py, evaluate_h30.py, verify_h30.sh,
validate_h30_corpus.py, measure_latency_h30.py, measure_machinery_h30.py, gen_h30_overlay.py}.
Gate 5 lessons applied (brief items 1-8): s6 (judge rules exact), s10 (judge audit as a gate step), s5.3 (record at first
observation), s2.4 (floors from the corpus), s5.5 (byte determinism), s8 (latency), EQUIVALENCE-G6 s4 (machinery), s5.1/s11 (one
launcher, refusals, freeze manifest incl. sealed corpus hash).

## 1. Oracle (pure; imports neither variant, no r3_harness, no HistoryStore, no variant self-report)
Reuses unchanged (hash re-listed): ops_model, authority_v2, scope_v2, constitution/const_* (only if A4 in scope), view/lowproj,
disclosure_reads, provenance, extoracle/extoutcome, continuity, recoverymodel. New r3_oracle/incident.py:
- taint(K, t_c, H) -> T*: committed requests/decisions whose authority path (oracle-recomputed, not the variant's authority_used)
  contains K or a K-derived element after t_c (PROT-H30 1.4); for K = adapter: every intent routed through it after t_c; for K =
  evidence store: every decision whose justification includes a record the TamperView changed; for K = authority version: every
  decision taken under it after its revocation time.
- minimal_containment(A, K) -> A' (PROT-H30 1.10), used for eligibility only.
- br_set(task, H) -> sorted list of typed strings (PROT-H30 1.6) from world_log (G5-E33 cross-checked), ExternalWorld ledger
  (root-key re-verified), harness read transcript vs lowproj, replay transcript.
- forbidden(H) -> the H23-H29 classes, computed by the same oracle calls the G5 judge uses (one decision oracle across gates).
- predict_recovery_view(H) -> G5 recoverymodel (RC2 rule).
- contained(probe window) -> bool: zero new BR elements and zero forbidden effects in the probe.
Isolation test C30-0 (AST closure scan + a known-negative copy importing paladin) at evaluate time -> invalid_if.

## 2. Corpus handling and generator role
2.1 No generator for the official corpus: the sealed tasks ARE the corpus. The harness interprets the DSL (rules.py, ONE rule table
    shared with the dev machine) - a test asserts DSL step kinds == machine rules (set difference, G5 Q14 pattern).
2.2 Replicates: perturbation(task, seed, r) changes only request ids, tick offsets inside task.slack and the legitimate workload
    sample; it is a pure function (seeded, derandomized); a test proves replicate 0 with zero slack == the task verbatim.
2.3 Hypothesis (contract role LIMITED): a RuleBasedStateMachine over the same rules explores dev tasks against FakeHonestG6 and
    both variants and SHRINKS any falsifier hit on dev; it never feeds the verdict.
2.4 Floors from the corpus only (G5-E30b): eligibility counts, per-class completion floors and the "attack non-vacuous" check are
    computed from the task + oracle (validator V3), never from variant replies.

## 3. Run of one (task, replicate, variant)
Fresh deployment ids for anchor / ExternalWorld / AuthorityService / identity service; variant host process (G5 P1g-6); the
harness executes the task steps on the absolute clock; at t_d the containment ladder (PROT-H30 s4) with probes; then the recovery
ladder (s5); then TAIL. Every service log, the world_log, the harness input log and transcript are captured. Workers: spawned pool,
each run independent, so results are order-free; byte-identical serial-vs-parallel check on the dev corpus is a pre-official gate.

## 4. Containment probe (exact)
Probe = the task's attacker.continuation executed for PROBE = 4 ticks (frozen) with the legitimate workload paused (so probe sends
never affect safe-progress counts); oracle contained() over exactly those sends. The probe's own sends are part of the BR window
(a probe that succeeds adds BR - that is the residual harm the rung failed to stop).

## 5. Recording (lesson 3: record at first observation; a missing record is a blocking harness row)
5.1 Every ladder action: rung, action, target, tick, reply - written when issued. Every probe: window, sends, contained flag.
5.2 Every host death: host_dead event at first notice (G5-E36 carried). Every refusal by P1h services is server-logged.
5.3 BR elements and taint items are recomputed by the oracle at finalize, but the RAW inputs (ledger rows, read replies) are in the
    transcript at the moment they are observed; a BR/taint computation that needs a fact absent from the record -> harness row
    `unrecorded_fact` (blocking: INCONCLUSIVE), never 0.
5.4 Evidence byte-determinism (lesson 5): every evidence file except latency-samples.jsonl.gz and latency-premium.json is a pure
    function of (corpus, seed, candidate); verify_h30.sh re-derives them and compares bytes. No wall-clock field anywhere else.
5.5 Harness rows: unsupported, host_spawn_failure, world_lock_timeout, unrecorded_fact, ladder_action_refused_by_plane (operator
    call failed for a plane reason), task_not_executable (a DSL step the harness cannot run for this task) -> the TASK is incomplete
    for both variants (never only one) and counts against the class completion floor.

## 6. Judge rules (lesson 1: exact implementation; each rule has a frozen-text pointer and a known-negative record)
J1 forbidden-effect classes: identical code paths to the G5 judge (commit order replay G5-E34a, LOOSE_PROPS G5-E27/E32, every reply
   status judged G5-E35 B4, every governed mutation kind incl. approve/delegate/revoke G5-E35 B6).
J2 BR: one set of typed strings per replicate; the task metric = median of the replicate set SIZES (integers, R odd); the sets
   are kept in evidence for attribution. Exemptions: none (an exemption needs an erratum).
J3 Containment actions and ticks from 5.1 records only; censoring rule PROT-H30 s4.
J4 Recovery actions and correctness PROT-H30 s5; taint comparison on sets of ids (exact, no loose form).
J5 Eligibility: continuity.classify SAFE_TO_RUN AND oracle OK under minimal_containment AND requester not in K AND not an
   input-invalid probe (G5-E30a); excluded by the corpus flag, never by a reply.
J6 Ratios and class status PROT-H30 s8 - computed in evaluator.py only from finalized rows.
Every rule J1-J6 gets a record-level known-negative test (forged row -> class fires) and a known-positive (honest row -> clean).

## 7. Evidence files per run directory (contract required_evidence names exactly) + verdict.json, manifest.json
blind-task-manifest.json (sealed hash, per task: id, class, source, adaptation, replicate seeds), per-class-security-results.json
(FE per class per variant with ids, recovery_incorrect, class status, intervals), blast-radius.json (per task/replicate/variant BR
set listed), containment-recovery.json (ladder records, actions, ticks, taint misses/falses, recovery diff paths),
safe-progress-comparison.json (pooled + per class + per phase, denominators), latency-premium.json, recurring-security-cost.json,
fairness-audit.json, tradeoff-frontier.md (generated from the JSON: per class (BR ratio, COST ratio) points + the premium axes; no
weighted score, docs/13:16), plus task-runs.jsonl.gz (raw), mutation-results.json, RAW_SHA256.txt.

## 8. Latency (lesson 6; contract support_if 5; docs/13:12 "steady-state p95 latency outside attack injection")
Procedure (scripts/measure_latency_h30.py, frozen; run by the same launcher after the task stage, never concurrently with it):
- Quiet-host gate: 1-min load average < 1.5 and no other run_h* process for 60 s before start, recorded; else refuse (non-dev).
- Same host, same services, same host RPC path (DeploymentProxy._rpc, r3_shared/host.py:261), client-side perf_counter_ns around
  each call; workload = frozen legitimate mix W (dependency-eligible operations of both domains over the overlay, reads and
  mutations in frozen proportions, no faults, no attack).
- Per run: warm-up 500 calls (discarded) then steady-state window 5,000 calls; p95 by the nearest-rank method.
- K = 6 runs in balanced order P C C P P C (fresh deployment each), plus an A/A calibration C C' and P P' (2 extra runs each).
- Pair ratios rho_i = p95(P_i)/p95(C_i), i = 1..3 (pairs in run order). PASS iff max rho <= 2.0; FAIL iff min rho > 2.0;
  otherwise UNCERTAIN. Calibration: A/A ratio outside [0.8, 1.25] for either variant -> measurement INVALID-for-latency ->
  INCONCLUSIVE (re-run allowed under a dev id first; official re-run of the latency stage only = Q-O6).
- Raw samples in latency-samples.jsonl.gz (sha256 in manifest; explicitly excluded from byte-determinism, 5.4).
- Also reported (descriptive): p50, p99, per-operation p95, host CPU model, Python version.
Known-negative: FakeSlowP (sleeps 3x per call) -> FAIL; FakeHonest vs itself -> PASS with A/A in band.

## 9. Mutation proof (contract mutation_proof) - meta-tests on the MEASUREMENT, run on the dev corpus before freeze and at evaluate
M-H30-1 biased cost accounting: an evaluator build that (a) multiplies conventional actions by 1.5, (b) drops Paladin's L6
        actions, (c) counts recovery diff paths only for conventional. Detection: verify_h30.sh recomputes COST independently from
        the raw ladder records (second implementation, scripts/recount_h30.py, no shared code with evaluator.py beyond canon_json)
        and refuses on any mismatch; meta-test asserts each biased build is caught.
M-H30-2 omitted baseline control: a conventional build with ONE HARDENING_LEDGER control disabled (one build per ledger row
        relevant to H30: identity revocation check, cap revocation check, effect-time authorization re-check, delegation-edge
        cascade, approval revocation, provenance verify-before-trust). Detection: ledger probes C30-L (one scripted probe per row,
        must fail on the disabled build and pass on the candidate); the launcher refuses an official run when any ledger probe fails
        on either variant (invalid_if "baseline capabilities"). Meta-test: each disabled build is caught by its own probe.
M-H30-3 denial counted as containment: FakeDenyAfterDetect (Paladin-shaped fake that answers DENIED to everything after t_d) and
        FakeGlobalFreeze (contains at L1 by suspending all principals internally). Detection: safe-progress regression > 5 pp ->
        verdict never SUPPORTED, per-class progress guard removes the class from MATERIAL. Meta-test asserts verdict != SUPPORTED
        and that a version of the evaluator WITHOUT the progress guard would have returned SUPPORTED (proves the guard is the
        deciding check, CLAUDE.md non-vacuity rule).
Plus the gate mutants of H23-H29 are NOT re-run (their gates are closed); C30 conformance re-runs each gate's dev regression.

## 10. Judge audit step (lesson 2; BLOCKING gate step, before the freeze commit that seals the corpus hash)
A1 An independent auditor (fresh agent, not the harness builder, not this designer) builds a rule-by-rule matrix: every rule of
   PROT-H30, this file, TASK-CORPUS-SPEC s3 and the G6 errata vs the implementing code (file:line), verdict CONFORMS / DEVIATES /
   UNTESTED-PATH, as spec/gate5/audit/judge-audit-matrix.md did.
A2 Scope includes the REUSED G5 modules and the 14 open G5 deviations (M04, M07, M15, M21, M23, M24, M27, M30, M38, M39, M48, M50,
   M52, M66) and M33: each is fixed or ruled "not reachable by H30 rules" with a test proving unreachability.
A3 Population sweep on dev evidence (dev corpus x both variants x 3 replicates + the fakes): for every class/metric, how many rows
   a plausible deviation would flip.
A4 Every DEVIATES that can flip a verdict is fixed before the freeze; the rest are listed in FREEZE_G6 as known deviations and in
   SUMMARY. Unreached paths get a scripted probe or are recorded UNTESTED.
A5 The audit reruns after any judge/evaluator change made after A1 (diff-scoped).

## 11. Freeze manifest (protocol/FREEZE_G6.json) - every file named in an invalid_if clause or a frozen rule
Specs: spec/protections/PROT-H30.md, spec/gate6/{ORACLE-AND-HARNESS-G6.md, EQUIVALENCE-G6.md, TASK-CORPUS-SPEC.md,
OPEN-QUESTIONS.md, task.schema.json, machinery-scope.json, latency-workload.json, workload-overlay/*.json, dev-corpus/*.jsonl,
sealed-corpus.json}, protocol/AUTHOR_DECISIONS_2026-10-15.md (+ G6 decisions file), protocol/thresholds.json, threat_model/{attack_
classes.json, security_invariants.json, survivability_envelope.json}, spec/gate5/envelope-ops.json, baselines/FAIRNESS.md,
protocol/DUAL_TRACK.json, protocol/HARDENING_LEDGER.jsonl (snapshot hash at freeze).
Harness/oracle: src/r3_harness/h30/*.py, src/r3_oracle/incident.py, src/r3_shared/opplane.py and changed r3_shared files
(identity.py, extworld*.py), reused oracle/judge modules (hashes re-listed from FREEZE_G5/G4), the H28 catalogue.
Measurement: scripts/measure_latency_h30.py, scripts/measure_machinery_h30.py, scripts/recount_h30.py, src/r3_harness/h30/evaluator.py.
Candidates: tags r3-g6-cand<N> (one tag covering both variants) and the variant tree hashes (git ls-tree of src/paladin, src/conventional).
Sealed corpus: primary_sha256, reserve_sha256, leaf_root, per-class counts. Seeds: official attempt seeds declared here (Q-A7).
Rule: test_freeze_g6_manifest.py parses THIS section + every invalid_if file list; run_h30.py calls the same function for non-dev ids.

## 12. Launcher (ONE launcher; refusals mirror every is_dev branch, G4-E27)
scripts/run_h30.sh --exp-id ID --variants paladin,conventional --corpus PATH --seed S [--replicates 3] [--latency] [--dev-overrides]
run_h30.py REFUSES (exit 2, no evidence dir) a non-dev id when: corpus sha256 != FREEZE_G6 (primary or the declared reserve);
HEAD != candidate tag; any FREEZE_G6 hash mismatch or manifest file missing; any service unreachable (anchor, ExternalWorld,
AuthorityService, identity/P1h); any ledger probe C30-L fails; quiet-host gate fails (latency stage); out dir exists; start method
!= spawn; dev overrides present. Dev ids (containing "-dev") may use the dev corpus and size overrides, stamped in verdict.json.
An AST test enumerates is_dev uses in evaluator.py and requires a matching refusal test.

## 13. Evaluator (src/r3_harness/h30/evaluator.py) -> contract + thresholds.json H30, 1:1
| Contract clause | Computed as | thresholds key |
|---|---|---|
| support: >= 5 classes, >= 40 tasks complete | classes meeting the completion floor >= 5 AND completed tasks >= 40 | min_attack_classes 5, min_blind_realistic_tasks 40 |
| support: 0 more forbidden effects in every class | for all c: FE_P(c) - FE_C(c) <= 0; count of classes violating <= 0 | max_attack_classes_with_candidate_forbidden_effect_regression 0 |
| support: >= 2 independent classes material | #MATERIAL classes (PROT-H30 8.3, distinct A-ids, survives fairness re-measure) >= 2 | min_classes_with_material_advantage 2; support_max_median_blast_radius_ratio 0.5; support_max_median_containment_or_recovery_cost_ratio 0.67 |
| support: safe progress <= 5 pp below | 100 x (ratio_C - ratio_P) pooled <= 5 | max_safe_progress_regression_percentage_points 5 |
| support: p95 ratio <= 2.0, machinery <= 2.5 | latency PASS (s8); machinery ratio (EQUIVALENCE-G6 s4) <= 2.5 | max_steady_state_p95_latency_ratio 2.0; max_recurring_security_machinery_ratio 2.5 |
| support: survives fairness audit | fairness-audit.json: every MATERIAL class re-measured against conventional' still MATERIAL | - |
| reject: safety regression | any class FE_P > FE_C, or recovery_incorrect_P > _C in a class (Q-A6) | - |
| reject: all parity/favor baseline | #MATERIAL == 0 AND #UNCERTAIN == 0 (Q-A3: with or without the "higher recurring cost" condition) | - |
| reject: advantage needs premium breach | #MATERIAL >= 2 but latency FAIL, or machinery > 2.5, or progress regression > 5 pp | - |
| reject: synthetic-only | by construction only sealed realistic tasks enter; dev/synthetic advantage reported, never counted | - |
| inconclusive | < 5 classes / < 40 tasks complete; #MATERIAL < 2 <= #MATERIAL + #UNCERTAIN; latency UNCERTAIN or A/A out of band; unresolved obvious control in fairness audit; harness rows | - |
| invalid | corpus hash mismatch; any FREEZE_G6 mismatch; variant tree changed after the sealing commit; oracle isolation C30-0 fails; transcript grep finds the sealed path/ids in a builder session (TASK-CORPUS-SPEC S7); class list/thresholds/ratio rules changed | - |
Precedence r3_shared.verdict.evaluate_common (INVALID > REJECTED > INCONCLUSIVE > SUPPORTED). verdict.json: {"h30_verdict",
"reasons", "per_class", "safety_record": {"paladin": {...}, "conventional": {...}}, "premium": {...}, "fairness": {...}} - the
safety_record is absolute per variant (FE, recovery_incorrect, BR totals) and descriptive.

## 14. Known-negative fakes (tests/fakes, never registered)
FakeHonestG6 (oracle-backed reference), FakeNoControls (no revocation checks; validator V3 non-vacuity reference), FakeLeaky
(disclosure after compromise), FakeTrustsTamper, FakeNoCascade (ignores edge cascade: BR grows), FakeTaintBlind (empty taint
report: recovery actions = |T*|), FakeDenyAfterDetect, FakeGlobalFreeze, FakeSlowP (latency), FakeStrawman (conventional with
a ledger control removed, M-H30-2). Each yields EXACTLY its expected class/metric set on the dev corpus.

## 15. Conformance before any dev run (both variants; FakeHonestG6 pass, matching fake fail)
C30-0 oracle isolation; C30-1 P1h adoption (identity revocation honoured within 1 tick; cap revocation refused server-side;
route quarantine); C30-2 taint_report form; C30-3 recovery after the ladder (RC2 rule) on scripted incidents; C30-L ledger probes
(one per HARDENING_LEDGER H30 row); C30-R regression: H23-H29 dev regression subsets byte-identical verdict classes on the G6 candidate.

## 16. Commands, runtime and order
dev:      scripts/run_h30.sh --exp-id exp-h30-dev1 --variants paladin,conventional --corpus spec/gate6/dev-corpus/dev.jsonl --seed 3011 --replicates 3 --latency --dev-overrides
smoke:    scripts/run_h30.sh --exp-id exp-h30-smoke-dev-1 ... --corpus spec/gate6/dev-corpus/dev.jsonl --seed 3012 --latency
official: scripts/run_h30.sh --exp-id exp-h30-001 --variants paladin,conventional --corpus <sealed primary> --seed 3021 --replicates 3 --latency
fairness: scripts/run_h30.sh --exp-id exp-h30-001-fa --variants paladin,conventional' --corpus <same> --seed 3021 (EQUIVALENCE-G6 s5)
Runtime estimate (to be replaced by a measured rate from dev1, two samples): H29 cost ~8 worker-s per sequence incl. mutants
(exp-h29-001r3 SUMMARY:3: 8,700 s x 6 workers / 6,400); an H30 task run ~150-300 steps + up to 6 probes + resume ~ 30-60 worker-s;
60 tasks x 3 replicates x 2 variants = 360 runs ~ 3-6 worker-h ~ 0.5-1 h wall at 6 workers; latency stage ~ 10 runs x 5,500 calls.
Order: P1h shared plane + overlay generator + schema + validator (one builder) -> task author: dev corpus -> oracle+harness+fakes
(one builder) || paladin seam || conventional seam (separate builders, PROT-H30 + P1h only) -> conformance C30 -> dev1 -> judge
audit (s10) + fixes -> equivalence audit (EQUIVALENCE-G6) -> task author: sealed corpora + citation audit -> FREEZE_G6 (variants,
harness, sealed hashes) -> smoke on dev corpus -> official -> fairness audit -> SUMMARY.
