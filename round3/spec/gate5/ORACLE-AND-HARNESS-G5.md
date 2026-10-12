# Gate 5 oracle, harness and evaluator design (H29)

DRAFT (g5-design 2026-10-12, HEAD d673a2c). Implements PROT-H29 + PROTOCOL-P1g. Packages: src/r3_oracle/continuity.py
(dependency classifier, authority-in-force, fault-state reconstruction), src/r3_oracle/recoverymodel.py (independent
lifecycle/replay model), src/r3_harness/h29/ (gen, faults, adapters_h29, host driver, runner, judge, mutation, evaluator,
evidence_out, finalize), scripts/{run_h29.sh, run_h29.py, evaluate_h29.py, verify_h29.sh, gen_depgraph.py}.
Lessons applied: reachability in the generator (G3-E28/E30), identical absolute clocks for paired runs (G4-E26),
frozen order/vocabulary/totality (G3-E17..E27), one launcher with refuse-if-missing services (G3-E31b), every
invalid_if hash clause in FREEZE_G5 + every dev/non-dev evaluator branch mirrored as a launcher refusal (G4-E27),
spawn-only workers with byte-identical serial-vs-parallel proof (G4 2026-10-10), caffeinate + gzip packing (G4).

## 1. Oracle (pure; imports neither variant, no r3_harness, no HistoryStore, no variant self-reports)

Inputs ONLY (PROT-H29 1.6 canonical history): frozen ops/auth specs, dependency-graph.json, envelope-ops.json,
systems.json; the harness input log (requests, approvals, schedule, crash arms, tamper ops); the AuthorityService log
(after close, key-verified lease macs); the anchor log (verify_anchor_log with the revealed key); the ExternalWorld
ledger (effects + audit + fault rows, root key re-verification as in G4); the observer transcript; the world_log of the
shared world store, used ONLY (a) to resolve the commit status of UNRESOLVED-class requests (in-doubt, crash in flight)
and (b) as the object of checks (its integrity is cross-checked against the anchor log: every OK commit mark has an
anchor entry; a mismatch is a harness/variant finding, never silently trusted).
Functions (total; absent -> explicit value, never an exception):
- fault_state(t) -> Phi(t) from the SERVICE fault logs + harness kill/resume log (not from the schedule alone: what the
  servers actually enforced is the truth; schedule vs server-log mismatch -> harness row injection_miss).
- authority_in_force(t) -> A(t) by the P1g-2 lease rule over the service log.
- classify(request, t) -> SAFE_TO_RUN | BLOCKED_BY_DEPENDENCY | UNRESOLVED (+ the down nodes of its deps) from the
  dependency graph + Phi(t) + LEASE only (PROT-H29 1.4). Never reads a reply.
- decide(request, state, A(t)) -> H23 ops_model.evaluate + H24 authority_v2 (one decision oracle across gates).
- low_view(principal, A(t), state) -> r3_oracle view/lowproj (H26) for R29-3.
- predict_world(H) -> world snapshot by applying the oracle decisions of committed requests in commit order (committed =
  SAFE OK requests + UNRESOLVED requests whose commit mark exists); must equal the WorldReader snapshot (else
  world_divergence -> recovery_divergence on the next RC, or harness row if no RC follows).
- predict_outcomes(I, transcript) -> P1f-6 via r3_oracle.extoracle (reuse, unchanged, FREEZE_G4 hash).
- predict_view(H, rc) -> RECOVERY_VIEW for RC2 (exact) and the admissible set for RC1 (PROT-H29 R29-10).
- explicit_expectation(request, class) -> the set of admissible replies (R29-6/R29-7 table) - used by the judge.
Isolation test C29-0 (AST closure scan + known-negative copy importing paladin) runs at evaluate time (invalid_if).

## 2. Generator (r3_harness/h29/gen.py) - reachability and envelope validity built in, never raises

A sequence = (domain, seed world, principals incl. one designated attacker agent for F7, a step list of 24-48 steps).
Step kinds (= the RuleBasedStateMachine rules, s3): request(op, principal, args, request_id, surface call_tool|direct),
approve, delegate, revoke, read, redeliver(request_id[, concurrent]), publish_authority(doc), fault_start(class, node,
mode, duration), fault_heal, crash(point, key), resume (implicit RC1), recovery_schedule (implicit RC2), tamper(kind),
advance(n), dispatch, reconcile(request_id).
Reachability (G3-E28/E30): worlds and every request's predicted state come from applying ops-spec operations through the
oracle model from the frozen seed; every ops-spec invariant is checked on the predicted snapshot; published authority
versions are drawn from a frozen family of v3 documents derived from spec/authority/<domain>.v3.json by REVOKING grants
or narrowing scopes only (schema-valid, every invariant intact) so stale use is detectable (s2.3); a draw that violates
anything is re-drawn and counted in gen-stats.
Stale-sensitivity (lesson "engineer input where hypotheses predict different numbers"): every F6 sequence contains >= 1
request whose oracle decision under the old version is OK and under the new version DENIED, sent after the new
version's effective tick (computed by the generator with the same lease rule) and while the variant may still hold the
old version (lease/outage/crash window). Same for R29-3 reads (a revoked disclosure rule).
Envelope validity: the generator enforces envelope-ops.json bounds (<= 2 concurrent classes, partition <= 2 nodes and
<= PARTITION_MAX, never {AUTH, ANCHOR, OBS}, one compromised identity, one tamper) - a draw outside -> re-drawn.
Progress-eligibility by construction: >= 60% of requests are oracle-OK; >= 50% of oracle-OK requests are scheduled while
a fault is active and their deps are up (unrelated healthy ops), so floors are met with margin.
Paired runs: RC1 A/B resume on the same absolute tick (G4-E26). No variant-vs-variant twin is needed (the oracle
classifies), so variants run independently on the identical corpus.
Strata (official): S-env >= 5,600 in-envelope sequences; S-ctrl >= 600 no-fault controls (same workload, no faults;
proves the safe-progress denominator is not a fault artefact and catches false alarms); S-bnd >= 200 catastrophic
boundary probes (B1-B4, >= 50 each). Per-class floors: >= 450 sequences with class Fk active, k = 1..8; per crash point
CP1..CP8 >= 60; per node >= 300 unrelated eligible requests. Pre-dev gate: 20,000-sequence generator sweep over 10
seeds, 0 exceptions, floors met at 10% scale.

## 3. Hypothesis role (PRIMARY)

r3_harness/h29/machine.py: a RuleBasedStateMachine whose rules are exactly the step kinds above, with @precondition
guards implementing the envelope bounds and @invariant checks calling the oracle after every step (safety, explicit
replies, progress bookkeeping). Used for (a) dev exploration against FakeHonest and each real variant, (b) SHRINKING any
falsifier hit on dev replays (shrunk trace stored next to the raw sequence, never replacing it). The OFFICIAL corpus is
a counted, reproducible list drawn from the same rule set by the seeded generator (derandomize=True, database=None,
G4 Q14): the machine's rules and the generator share one rule table (r3_harness/h29/rules.py, frozen) so they cannot
drift; a test asserts that every generator step kind is a machine rule and vice versa (set difference).

## 4. Fault catalogue (r3_harness/h29/faults.py; frozen; maps envelope class -> injector -> expected oracle consequence)

| id | injector (P1g) | expected (oracle) |
|---|---|---|
| F1-CPn | arm CPn at key, SIGKILL, resume (RC1, RC2) | in-flight request UNRESOLVED; committed set exact at RC1; no duplicate after redelivery |
| F2-out | AuthorityService outage(drop) [a,b) | requests inside the lease window SAFE (must progress, R29-0); after it BLOCKED (UNAVAILABLE AUTH) |
| F2-rl  | AuthorityService partition(reply_lost) | lease granted server-side but unseen; same classification as F2-out |
| F3-down | ExternalWorld outage(S) | decisions SAFE; intents on S PENDING/UNKNOWN; other systems' intents SAFE |
| F3-byz | frozen H28 catalogue primitive on S (L1..G3) | H28 classes (effect_outside_scope, false_reconciled_success, duplicate_effect) |
| F4-dup | redeliver request_id (sequential / concurrent 2-3 copies) | one commit, original decision repeated |
| F4-ord | approve after request; reconcile watermarks out of order; O2 delay; observer lag | oracle decisions per actual order; outcome monotone (G4-E16) |
| F5-part | partition {node} or {node1, node2}, drop / reply_lost | per-node BLOCKED/UNRESOLVED; unrelated ops SAFE |
| F6-stale | publish(narrowed doc) during lease / outage / crash window | stale-sensitive request must be DENIED (or UNAVAILABLE AUTH), never OK |
| F7-comp | attacker agent schedule | P1/P2 classes 0 |
| F8-tamper | TamperView op on continuation records while host dead | R27-5: non-OK with zero effect or exactly untampered behaviour; replay TAMPERED/UNRESOLVED |
Note on F2: every governed mutation depends on AUTH (P1g-4). With R29-0 (lease-backed continuity, recommended Q5) the
F2 during-fault ratio of PROT-H29 s5 (i) is measured on lease-window requests; without R29-0 it would be empty (global
stop by graph) and F2 would be judged on explicitness and staleness only - the evaluator then reports F2 (i) as
"not applicable by graph" and the floor moves to F3/F5. The generator places >= 40% of F2 outages within LEASE-1 ticks
after a governed request so lease windows exist.

## 5. Runner and launcher (ONE launcher for dev, smoke and official; services refused-if-missing)

scripts/run_h29.sh --exp-id ID --variants a,b [run_h29.py flags]: per variant starts the H27 anchor, the ExternalWorld
server and the AuthorityService outside the sandbox; runs run_h29.py under run_sandboxed.sh (writes denied to the
anchor, ext and auth dirs), under `caffeinate -dimsu`; closes all three and records close() output; asserts no leaked
server processes at exit (ps check, G4 orphan lesson).
run_h29.py REFUSES (exit 2, no evidence dir) a non-dev id when ANY of: anchor / ExternalWorld / AuthorityService socket
unreachable; HEAD != candidate tag; any FREEZE_G5 hash mismatches or any file of the freeze manifest (s9) is missing
from FREEZE_G5 (the same freeze_state()/catalogue_state() helpers the evaluator uses); dev overrides present; sizes below
the frozen floors; out dir exists; multiprocessing start method != spawn.
Per sequence: fresh deployment ids for anchor stream / ext / auth; a variant host (P1g-6) per incarnation; the harness
executes exactly the generated steps; final RC2 for every open recovery; the final world/anchor/ledger/auth logs are
captured per sequence. Workers: spawned pool (R3_H29_WORKERS), each sequence fully independent (own world file, own
deployment ids) so results are order-free; a byte-identical serial-vs-parallel check on 200 sequences is a pre-official
gate.

## 6. Classification (judge = r3_harness/h29/judge.py over oracle output; one row per (sequence, variant))

Per request: oracle class, admissible reply set, actual reply, commit evidence, classes hit. Per recovery event: RC1
determinism (A/B digests), RC1 admissibility diffs, RC2 diff (field paths), redelivery check. Per sequence: classes of
PROTOCOL/PROT-H29 s8, progress bookkeeping (eligible/progressed per class, per node, post-recovery), boundary result.
Harness rows (make the run INCONCLUSIVE, except where noted): unsupported (NotImplementedError ... G5), host_spawn_failure,
world_lock_timeout, generator_redraw_exhausted, injection_miss (scheduled fault not enforced by the server log or armed
crash point never fired before the sequence ended) -> INVALID when the per-class hit rate falls below the s7 bound.

## 7. Evidence files per variant directory (contract names exactly) + verdict.json, manifest.json

- fault-sequences.jsonl: one line per sequence: id, stratum, seed, domain, world digest, full step list, Phi timeline
  (from server logs), every request + reply + oracle class + admissible set, crash/kill/resume records, RC1/RC2 digests,
  dependency_status snapshots (descriptive), classes. (gzip when > 2 MB; RAW_SHA256.txt.)
- safety-invariants.json: per class of R29-1..R29-5 the count and exact sequence/request ids; P1-P5 totals; boundary
  B1-B4 results.
- safe-progress.json: overall ratio; per fault class during-fault ratios; per node unrelated ratios; post-recovery ratio;
  denominators, floors met/unmet; outcome_progress_loss; spurious_unavailable per node.
- explicit-unavailability.json: per request with a dependency down: class, reply, verdict; misclassification count with
  ids broken down by kind (OK / DENIED / INVALID-non-input / UNAVAILABLE-misattributed / UNKNOWN-other / outcome-plane).
- recovery-differential.json: per recovery event: crash point, RC1 A/B equal, RC1 admissibility diffs, RC2 oracle view vs
  variant view (both canonical JSON, digest + diff paths), redelivery check; equality ratio.
- mutation-results.json: per KNOWN["H29"] mutant: subset, own-class count + ids, clean-build count on the same class
  (must be 0), killed.
- injection-effectiveness.json (extra): per fault class / node / crash point: windows scheduled, windows enforced (server
  log), windows with >= 1 refused call from the deployment, crash points fired; hit rates.
- verdict.json, manifest.json (sha256 of every evidence file, FREEZE_G5 hashes, candidate tag, close() outputs of the
  three services, evaluator sha256, thresholds sha256).
Size budget: < 50 MB per run after gzip (estimate 5,600 x 2 variants x ~40 steps ~ 450k request lines ~ 300 MB raw,
~25-35 MB gzipped); if exceeded, fault-sequences.jsonl keeps every step but drops world snapshots (digests only).

## 8. Evaluator (r3_harness/h29/evaluator.py) -> contract + thresholds.json H29, 1:1

| Contract clause | Computed as (raw rows only) | thresholds.json key |
|---|---|---|
| support: 0 P1-P5 safety violations inside the envelope | sum of R29-1..R29-5 classes over S-env == 0 | max_safety_invariant_violations 0 |
| support: safe-progress >= 0.95 | overall ratio >= 0.95 AND every PROT s5 (i)-(iii) ratio >= 0.95 (Q4) | min_safe_progress_ratio_when_dependencies_available 0.95 |
| support: 0 dependency failures misclassified | misclassified_dependency_failure == 0 | max_dependency_failure_misclassifications 0 |
| support: 100% recovery-state equality | (RC1 determinism + RC1 admissibility + RC2 equality) passes / recovery events == 1.0 | required_recovery_state_equality 1.0 |
| support: 100% target mutations detected | killed / len(KNOWN["H29"]) == 1.0 | required_mutation_kill_rate 1.0 |
| support/inconclusive: >= 5,000 mixed sequences | S-env sequences >= 5,000 | min_fault_sequences 5000 |
| reject_if | any safety class > 0 OR recovery equality < 1.0 OR any progress ratio < 0.95 OR misclassification > 0 (Q8) OR boundary_not_explicit > 0 (Q6) | - |
| inconclusive_if | any envelope class (F1..F8) with < 450 active sequences or 0 (corpus omits a class); S-env < 5,000; oracle cannot distinguish blocked from healthy: per node, BLOCKED >= 100 AND SAFE-during-fault >= 300 requests not met; any PROT s5 floor unmet; outcome_progress_loss floor; harness rows | - |
| invalid_if (a) injection not on the real path | per fault class: enforced-window rate < 1.0 (server log disagrees with schedule) OR (F2/F3/F5) windows with >= 1 refused call from the deployment < 0.5 OR any armed CP never fired in its sequence | - |
| invalid_if (b) recovery uses candidate state as its own oracle | C29-0 AST isolation scan of r3_oracle/{continuity,recoverymodel,extoracle,ops_model,authority_v2,view,lowproj} closure fails; or oracle inputs list (manifest) contains a variant-written file other than the world store | - |
| invalid_if (c) envelope narrowed after failures | sha256 of threat_model/survivability_envelope.json, spec/gate5/envelope-ops.json, spec/gate5/dependency-graph.json, r3_harness/h29/faults.py, r3_harness/h29/rules.py != FREEZE_G5 | - |
| invalid_if (d) integrity | any FREEZE_G5 hash or evidence hash mismatch; H28 catalogue sha != FREEZE_G4 entry; service close() keys fail log verification | - |
Precedence via r3_shared.verdict.evaluate_common (INVALID > REJECTED > INCONCLUSIVE > SUPPORTED); two verdicts plus the
DUAL_TRACK comparative record (forbidden_effects, safe_progress_ratio, mutation_kill_rate, p95_latency_ms from the host
RPC round trip, security_specific_loc, security_specific_components).
Dev ids (suffix -dev*) may override sizes; overrides are stamped in verdict.json; evaluate refuses them on non-dev ids.
EVERY branch of the evaluator that differs for dev vs non-dev ids is listed here and mirrored as a run_h29.py refusal
(lesson G4-E27): (1) size overrides; (2) freeze manifest completeness (any s9 file absent from FREEZE_G5 -> non-dev
INVALID / launcher refusal); (3) service presence (anchor, ext, auth close() outputs required); (4) candidate tag check.
A unit test enumerates `is_dev` uses in evaluator.py by AST and fails when one has no matching launcher refusal test.

## 9. Freeze manifest (protocol/FREEZE_G5.json) - every file named in an invalid_if clause or a frozen rule

Specs and design: spec/protections/PROT-H29.md, spec/gate5/{PROTOCOL-P1g.md, ORACLE-AND-HARNESS-G5.md,
EQUIVALENCE-G5.md, OPEN-QUESTIONS.md, dependency-graph.json, envelope-ops.json, reason-map.json},
protocol/AUTHOR_DECISIONS_<G5 date>.md, threat_model/survivability_envelope.json, threat_model/security_invariants.json,
schemas/dependency-graph.schema.json, the narrowed authority-version family spec/gate5/authority-versions/<domain>/*.json.
Fault injection (invalid_if a/c): src/r3_harness/h29/faults.py, src/r3_harness/h29/rules.py,
src/r3_harness/h29/adapters_h29.py, src/r3_shared/faultplane.py, src/r3_shared/authsvc.py, src/r3_shared/authsvc_server.py,
src/r3_shared/host.py, plus the H28 catalogue src/r3_harness/h28/adapters.py (hash re-listed from FREEZE_G4).
Oracle model (invalid_if b): src/r3_oracle/continuity.py, src/r3_oracle/recoverymodel.py (extoracle.py, ops_model.py,
authority_v2.py, view.py, lowproj.py hashes re-listed from earlier freezes - a change there must be visible to G5).
Evaluator: src/r3_harness/h29/evaluator.py (its sha256 also stamped in verdict.json, H28 pattern).
Rule: a test (test_freeze_g5_manifest.py) parses THIS section and the evaluator's invalid_if file list and fails if any
path is missing from FREEZE_G5 or any FREEZE_G5 path is missing on disk; run_h29.py calls the same function for non-dev
ids (refusal). Appending an erratum to spec/gate5/OPEN-QUESTIONS.md refreshes its FREEZE_G5 hash in the same commit
(G3 lesson).

## 10. Known-negative fakes (tests/fakes, never registered) - each yields EXACTLY its expected class set

FakeHonestG5 (oracle-backed reference: SUPPORTED at dev size with stamped overrides), FakeFailOpenAuth (->
stale_authority_commit + forbidden_effect), FakeGlobalHalt (-> progress ratios < 0.95 only), FakeStaleRestart (->
stale_authority_after_restart), FakeRandomRecovery (-> recovery_nondeterministic), FakeDenyOnOutage (->
misclassified_dependency_failure only), FakeDropOutbox (-> recovery_divergence + misclassification outcome-plane),
FakeAckBeforeAnchor (-> unanchored_ack), FakeEmptyOnLoss (B4: starts empty after store deletion -> boundary_not_explicit
+ duplicate_commit), FakeAlwaysUnavailable (UNAVAILABLE for everything -> progress < 0.95 and spurious_unavailable;
never SUPPORTED), FakeMisattributes (names ANCHOR when AUTH is down -> misclassification), FakeSurvivesCoopCrash (module
cache surviving cooperative crash; must show stale class ONLY because hard restart kills it -> proves P1g-6 works: expected
0 classes), FakeOracleImporter (oracle copy importing paladin -> INVALID b).

## 11. Conformance against BOTH real variants BEFORE any dev run (each also on FakeHonestG5 = pass, matching fake = fail)

C29-0 oracle isolation (AST scan + known-negative). C29-1 seam adoption: with authority_source given, zero calls to
set_authority from the harness and >= 1 fetch per decision lease window (server log); with it None the H23/H28 paths are
byte-identical to the G4 candidates on their differential subsets. C29-2 crash points: every CP1-CP8 fires for both
variants on scripted probes (set difference over points; an unfired point is a seam defect, fixed before dev). C29-3
lease rule: >= 2,000 scripted (publish, fetch, decide) schedules; every committed authority_version == A(t). C29-4 reply
vocabulary: every node outage x every surface -> admissible reply only. C29-5 recovery_view: RC1 A/B determinism on 500
scripted kills; RC2 equality on the same. C29-6 resume refusal: deleted store -> CanonicalStateLost. C29-7 dependency
graph: generated == committed; variants read it as data (static scan: no per-domain dependency literals in variant code,
G3-E29 resolution rules apply).

## 12. End-to-end chain test (tests/test_h29_e2e.py; G3-E31b lesson)

Runs scripts/run_h29.sh --exp-id exp-h29-e2e-dev-1 (16 sequences incl. one per fault class, FakeHonestG5 and
FakeFailOpenAuth) -> evaluate -> verify_h29.sh, asserting: the three services were started by the launcher and closed
(no leaked processes); verdicts SUPPORTED (dev-stamped) / REJECTED; a non-dev id with each service stopped exits 2 with
no evidence dir (three cases); a non-dev id with a manifest file missing from FREEZE_G5 exits 2; a changed frozen file ->
INVALID; serial and 2-worker parallel runs of the same seed give byte-identical evidence.

## 13. Commands (ONE launcher; only ids and sizes differ) and runtime estimate

    dev:      scripts/run_h29.sh --exp-id exp-h29-dev1 --variants paladin,conventional --seed 2911 --sequences 560 \
              --controls 60 --boundary 40 --dev-overrides
    smoke:    scripts/run_h29.sh --exp-id exp-h29-smoke-dev-1 --variants paladin,conventional --seed 2912 --sequences 250
    official: scripts/run_h29.sh --exp-id exp-h29-001 --variants paladin,conventional --seed <declared in the freeze
              commit: 2921/2922/2923 for attempts 1-3> --sequences 5600 --controls 600 --boundary 200
    evaluate: scripts/evaluate_h29.py experiments/h29/<id>      verify: scripts/verify_h29.sh experiments/h29/<id>
Mutation proof: run_h29.py --mutants runs each KNOWN["H29"] build on a frozen 1,400-sequence subset stratified so each
mutant's killing class has >= 150 sequences (F2/F6 for fail_open/stale, F1 for recovery mutants, F3/F5 for global halt,
ANCHOR partitions for anchor_skipped).
Runtime (from exp-h28-001r: ~19,400 deployments in 31 min for Paladin with spawned workers, Paladin ~16 lines/s vs
conventional ~40 lines/s): an H29 sequence is ~8x an H28 case (40 steps, 1-3 host spawns ~0.5-1 s each, RC1 doubles
resumes). Estimate per variant: 6,400 sequences x ~3 s + 1,400 x 7 mutants x ~3 s ~ 35 h CPU -> ~3-4.5 h wall at 8-10
workers; Paladin dominates. Plan official runs for ~5 h under caffeinate; measure the real rate on dev1 (2 samples)
before quoting an ETA (CLAUDE.md rule).
Official order: fresh worktree per candidate, HEAD == tag asserted after checkout, full sharded suite quiet-host green,
smoke on the exact candidate with the byte-identical launcher, then official; variants as 2 parallel processes (p95
descriptive only); push after each evidence commit.

## 14. Build order (bounded shared steps first)

P1g (r3_shared + tests + dependency-graph/envelope-ops + FREEZE_G5 draft) -> oracle + harness + fakes + conformance (one
builder) || paladin seam || conventional seam (separate builders from PROT-H29 + P1g only) -> integration: C29-0..7 +
H23..H28 regression -> freeze manifest test green -> dev1 -> errata -> smoke -> official.
