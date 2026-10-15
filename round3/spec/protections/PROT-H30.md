# Protection and measurement specification H30 - comparative operational-security value (both variants)

DRAFT (g6-design 2026-10-15, round3 HEAD 3588afe, read-only). Given to BOTH variant builders and to the harness/oracle builder.
It contains NO task, NO incident source and NO class quota beyond what the contract already states (blindness, AUTHOR_DECISIONS_2026-10-15 s1).
Sources: hypotheses/h30/contract.json (evaluator lines), protocol/thresholds.json "H30", docs/13_measurement_model.md:5-18,
docs/08_evidence_and_fairness.md:35-37, baselines/FAIRNESS.md:3-21, protocol/DUAL_TRACK.json, threat_model/*.json.

## 0. What H30 is and is not
- H30 adds NO new security property. P1-P6 are already tested part-by-part by H23-H29 (all SUPPORTED for both variants, s9).
  H30 measures whether the COMPOSITION gives Paladin a material operational-security advantage over the conventional variant on
  blind, cited, realistic multi-step incidents, without a safety regression and inside the premium limits.
- Gate-level parity is the expected null: every H23-H29 official run recorded parity (e.g. experiments/h29/exp-h29-001r3/SUMMARY.md:52,65).
  A REJECTED H30 is a valid outcome (docs/11_definition_of_done.md:16).
- One comparative verdict (s8). Each variant's absolute safety record is reported beside it, never as a second H30 verdict.

## 1. Definitions (frozen)
1.1 Task. A sealed, cited, multi-step incident scenario in the frozen task DSL (TASK-CORPUS-SPEC.md s2) over the frozen H30
    workload overlay (s1.9). Exactly one PRIMARY attack class (A1..A10 id); optional secondary tags. Realistic tier only.
1.2 Phases of a task run (logical ticks, L3 as in G5): WARM [0, t_c) legitimate workload only; COMPROMISE at t_c (the task's
    compromised boundary becomes attacker-controlled); ATTACK [t_c, t_d) attacker steps interleaved with legitimate workload;
    DETECT at t_d (fixed by the task, identical for both variants: detection is NOT measured, it is an input); CONTAIN [t_d, t_k)
    operator ladder (s4) until containment is verified; RECOVER [t_k, t_r) recovery ladder (s5); TAIL [t_r, t_end) legitimate
    workload + attacker continuation (the attacker keeps trying every avenue the task lists) to catch residual harm.
1.3 Compromised set K: the task's compromised boundary (one principal identity, one adapter/system, one mutable evidence store,
    or one authority-document version), as listed in the task's incident report. Never wider than the survivability envelope
    (threat_model/survivability_envelope.json fault_classes; catastrophic_boundary excluded).
1.4 Tainted request (oracle): a committed request whose authority path (H24 authority_used path, H25 governance path where used)
    contains an element of K or an element DERIVED from K after t_c (a delegation edge created by K, an approval given by K, an
    intent submitted through a compromised adapter, a decision justified by a tampered record). Computed ONLY by the oracle from
    canonical history (s7); never from a variant self-report.
1.5 Forbidden effect: an effect the oracle decides is NOT authorized under the LEGITIMATE authority in force (H23-H29 classes:
    forbidden_effect, effect_outside_scope, stale_authority_commit(_after_restart), disclosure_leak, tampered_record_trusted,
    duplicate_commit/duplicate_effect, false_success/false_reconciled_success, unanchored_ack). An effect inside the capability
    legitimately issued to K before detection is NOT forbidden (A1 by definition) but IS in the blast radius.
1.6 Blast radius BR(task, variant): the number of DISTINCT elements of
      { world object refs (type:key) changed by a tainted or forbidden committed request }
    U { ExternalWorld (system, target) pairs with an applied effect row of a tainted or forbidden intent }
    U { protected object refs disclosed to a principal in K outside the oracle low view (H26 lowproj) }
    U { decision_ids whose tampered provenance was accepted as VERIFIED or acted on }
    over [t_c, t_end] (attack window AND residual after containment). Elements are typed strings "obj:", "ext:", "disc:", "prov:";
    the union is a set of strings (no weighting, docs/13:3). Ground truth: world_log, ExternalWorld ledger, harness read transcript
    vs oracle low view, anchor + replay transcript (s7).
1.7 Operational cost COST(task, variant) = containment actions + recovery actions (s4, s5): integer count of operator actions.
    Reported beside it: containment ticks (t_k - t_d), recovery ticks (t_r - t_k), each component separately.
1.8 Safe progress: legitimate (non-K, non-attacker) requests that are dependency-eligible (H29 continuity.classify == SAFE_TO_RUN)
    AND whose oracle decision under the MINIMAL CONTAINMENT STATE (s1.10) is OK; progressed = committed with the oracle decision
    (and, for external effects, RECONCILED_SUCCESS per G5-E35 B2). Ratio per variant pooled over all tasks and per class.
1.9 H30 workload overlay (spec/gate6/workload-overlay/<domain>.json): a larger, public, frozen seed world for both public Round 2
    domains (manufacturing, project): more principals, agents, service accounts, delegation chains, resources and external
    systems, so blast radius has room to differ. Derived from spec/ops + spec/authority + spec/external by a frozen generator
    script; every ops-spec invariant holds on it; built and frozen BEFORE the task author starts; tasks may reference only its ids.
1.10 Minimal containment state (oracle): the legitimate authority in force with exactly K's authority removed (K's grants, edges,
    approvals, caps, K-derived elements) and nothing else. A legitimate request outside K that this state allows is eligible:
    denying it because containment was over-broad is lost progress (mutation proof M-H30-3, s10).

## 2. Seams (equal for both variants; DUAL_TRACK)
Existing seams only, plus ONE shared operator plane (P1h, shared code like P1f/P1g) and TWO pure variant self-reports:
2.1 P1h operator plane (shared, variant-neutral, server-side, built by the harness/P1h builder):
    - IdentityProvider revocation: revoke(subject) and revoke(token) with a revocation list served by the identity service;
      TokenVerifier checks it (shared library; both variants verify tokens through it already, r3_shared/identity.py:52-74).
    - AuthorityService publish (exists, r3_shared/authsvc.py:204) - narrowing documents built by a frozen narrowing function (G5-E1 form).
    - Deployment.revoke(edge) (exists, H24) for delegation edges, called with an operator token.
    - ExternalWorld cap revocation: revoke_chain(root nonce | chain id) and route quarantine(system, deployment); checked
      server-side before effect (r3_shared/extcap.py has no revocation today).
    - set_governance (exists, H25) only if Q-A9 includes A4.
    Each call is ONE operator action. The plane is shared because the conventional baseline must receive the same class of
    identity/credential revocation the candidate has (FAIRNESS.md:7-14); a variant that ignores a revocation shows it as BR.
2.2 taint_report(incident) -> {"requests": [request_id...], "decisions": [decision_id...]} : pure self-report of what the variant
    believes is tainted by K (input: the frozen IncidentReport form: K, t_c, t_d, indicators). Judged against the oracle taint set;
    never ground truth (Variant protocol rule, r3_shared/variant.py:3-5).
2.3 recovery_view() (exists, G5 P1g-8) extended by nothing; reused after the recovery ladder.
2.4 Missing seam -> NotImplementedError("not implemented yet - G6") -> harness row `unsupported` (INCONCLUSIVE), as G2-G5.

## 3. Attack execution
Attacker capabilities come ONLY from the frozen primitives of earlier gates (H23 compromised token + direct/call_tool, H24
delegate/revoke/stale replay, H25 constitutional where enabled, H26 read/list/query/subscribe/prov probes, H27 TamperView ops,
H28 Byzantine adapter catalogue src/r3_harness/h28/adapters.py (FREEZE_G4 hash), H29 fault plane + crash points, PROT-H23-A8
concurrency/redelivery) and the P1h operator plane (attacker never holds an operator token). No task-specific harness code.

## 4. Containment ladder (variant-neutral, frozen; operator = harness)
At t_d the harness executes the frozen ladder L1..L6, ONE action per tick, and after each action runs the containment probe
(attacker continuation replayed against the deployment for PROBE ticks; contained iff the oracle sees zero new tainted or
forbidden effects and zero new disclosures in the probe). The first clean probe sets t_k; later rungs are not run.
  L1 revoke K's identity (P1h identity revoke) [K = principal] / quarantine K's route [K = adapter] / mark store [K = evidence store]
  L2 publish the narrowed authority document removing K's grants (frozen narrowing function)
  L3 revoke every delegation edge created by or to K - edges taken from the HARNESS input log (never from the variant or oracle)
  L4 revoke every ExternalWorld cap chain issued for K's requests (from the harness input log + ExternalWorld audit)
  L5 cancel K's open approvals (approve-with-revoke per H24 R24 rules) listed in the harness input log
  L6 global freeze: suspend every agent principal of the overlay (always contains; destroys safe progress - counted)
The ladder is derived from the incident report and the harness's own log only, so both variants get the identical operator.
Containment actions = number of actions executed (each element of a rung's list is one action). Not contained after L6 ->
censored: actions = all ladder actions + 1, t_k = t_end, BR keeps counting.

## 5. Recovery ladder and correctness
R1 call taint_report(incident); oracle compares with the true taint set T*: every missed element and every false element = ONE
   operator action (manual investigation), recorded as recovery_taint_miss / recovery_taint_false.
R2 restart the variant host from durable state (deploy(resume=True), G5 host) - one action - and compare recovery_view() with the
   oracle's prediction (G5 R29-10 RC2 rule, canonical JSON); every differing field path = ONE operator action (manual repair).
R3 replay(decision_id) for every decision of T* (H27): a tampered decision answered VERIFIED = tampered_record_trusted (forbidden).
Recovery correct iff R1 has 0 misses and 0 false, R2 has 0 diff paths, R3 has 0 trusted tampered records.
Recovery actions = 1 (R2) + misses + falses + diff paths. recovery_incorrect(task, variant) = not correct (a SAFETY-RECORD class, s6).

## 6. Per-task outputs (one row per (task, replicate, variant))
forbidden_effects (by H23-H29 class), BR set (elements listed), containment actions/ticks/rung reached, recovery actions/ticks,
recovery_incorrect, taint misses/falses, eligible/progressed counts (pooled + per phase), harness rows. Replicates (s8.2):
integer metrics per task = median of replicates (odd R); forbidden effects = SUM over replicates (any hit counts).

## 7. Oracle independence (see ORACLE-AND-HARNESS-G6 s1)
Imports neither variant (AST closure scan, invalid_if). Reads only: frozen specs + overlay, the task file, the harness input log,
AuthorityService log, anchor log, ExternalWorld ledger, identity revocation log (P1h), observer transcript, and world_log under the
G5-E33 cross-checks (the only variant-process file; L8 of G5 carried forward).

## 8. Measurement and verdict (thresholds.json H30, 1:1; full table in ORACLE-AND-HARNESS-G6 s8)
8.1 Per-task ratios (Paladin/conventional), zero-denominator rule (contract support_if 3): C=0,P=0 -> 1.0 (absolute parity);
    C>0,P=0 -> 0.0 (strict advantage); C=0,P>0 -> +inf (strict disadvantage); else P/C. Applies to BR and COST separately.
    A task where Paladin's recovery is incorrect and the baseline's is correct gets COST ratio +inf.
8.2 Replicates: R = 3 seeded non-semantic perturbations per task (request ids, tick offsets inside the task's stated slack,
    legitimate workload sample); the realistic task is the unit, replicates are not extra tasks.
8.3 Class statistic: median of per-task ratios over the class's completed primary tasks, with the distribution-free
    order-statistic interval [x(lo), x(hi)] (n = 10: x(3), x(8), coverage 0.891; table for n = 8..12 frozen in evaluator).
    Class MATERIAL iff (BR: x(hi) <= 0.50) OR (COST: x(hi) <= 0.67), AND the class's safe-progress regression <= 5 pp.
    Class EXCLUDED_MATERIAL iff for both metrics x(lo) > threshold. Otherwise UNCERTAIN. (Q-A4: alternative = point median.)
8.4 Independent classes = distinct primary A-ids; every public source backs tasks of ONE class only (TASK-CORPUS-SPEC s4).
8.5 Safety: forbidden effects per class FE_P(c) <= FE_C(c) for EVERY class (thresholds max_attack_classes_with_candidate_
    forbidden_effect_regression 0); recovery_incorrect per class P <= C (safety-record class, Q-A6).
8.6 Safe-progress regression = 100 x (ratio_C - ratio_P) pooled over dependency-eligible work <= 5 pp; per class reported and
    used in 8.3.
8.7 Latency (s8 of ORACLE-AND-HARNESS-G6): steady-state p95 ratio <= 2.0 by the frozen latency procedure.
8.8 Recurring security-specific machinery ratio <= 2.5 by the frozen method (EQUIVALENCE-G6 s4, Q-A5).
8.9 Fairness audit (EQUIVALENCE-G6 s5): MATERIAL classes must survive the post-reveal fairness re-measure.

## 9. Upstream (contract upstream_dependencies H23-H29; docs/12:20)
H23 exp-h23-002, H24 exp-h24-001, H25 exp-h25-003, H26 exp-h26-003, H27 exp-h27-001, H28 exp-h28-001r, H29 exp-h29-001r3: SUPPORTED
for both variants (experiments/hNN/<id>/verdict.json). No upstream stop. Caveat carried: H29 holds under a judge with 14 open audit
deviations and the untested M33 path (exp-h29-001r3/SUMMARY.md:17); H30 reuses those judge modules, so the G6 judge audit (OH-G6 s10)
must cover them (Q-O4).

## 10. Mutants and meta-tests (contract python_hypothesis_role.mutation_proof; detail in ORACLE-AND-HARNESS-G6 s9)
M-H30-1 biased cost accounting; M-H30-2 omitted baseline control; M-H30-3 candidate denial counted as containment without
safe-progress accounting. Each must be detected (evaluator verdict changes / meta-test red) on the frozen dev corpus.

## 11. Scope limits (declared; every SUMMARY repeats them)
L1-L8 of G5 carried forward. G6 adds: L9 detection time is an input (t_d fixed by the task), not measured; L10 operator =
frozen variant-neutral ladder (no human, no variant-authored runbook); L11 latency is wall-clock on one host (noise reported, A/A
calibration); L12 incidents are ADAPTED to two research domains via a frozen overlay - realism is "pattern-faithful", stated per task.
