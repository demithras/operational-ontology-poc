# Protection specification H29 - safe continuity and deterministic recovery inside a bounded fault envelope (both variants)

DRAFT (g5-design, 2026-10-12, repo HEAD d673a2c, read-only). Requirement-level; the ONE place the H29 rules are written;
r3_oracle/continuity.py, both variants and r3_harness/h29 implement exactly this text. Invariant P6_SAFE_CONTINUITY
(threat_model/security_invariants.json); safety = P1-P5 under the faults of threat_model/survivability_envelope.json.
Contract: hypotheses/h29/contract.json. Protocol: PROTOCOL-P1g.md (P1g-1..P1g-10). Upstream: H24 (authority graph,
commit boundary, R24-7 progress), H27 (envelope, anchor before ack R27-6, continuation R27-5), H28 (outbox, caps,
outcome function P1f-6, observer). H23 supplies the decision oracle and request_id idempotency (R5).

## 0. Current seam (as found at d673a2c) and why H29 cannot be measured on it

- crash()/restart()/arm_crash() are COOPERATIVE and in-process: the variant itself decides what "lost memory" means
  (Paladin `_die` drops `self._c`; conventional `crash()` clears `_mem_ledger`, `_policy`). A module-level or object-level
  cache that survives a cooperative crash is invisible, so "stale cache retained after restart" cannot be measured.
- Authority is PUSHED by the harness through set_authority(spec) and becomes a world transaction (PROT-H24 s4). There is
  no authority/policy DEPENDENCY that can be unavailable, partitioned or stale: the envelope class "single policy or
  authority dependency unavailable" has no real path to hit.
- Only two crash points exist (before_commit, after_commit). "Restart mid-outbox", "crash during reconcile", "crash during
  recovery" and "reply lost after anchor append" have no injection point.
- No reply vocabulary separates dependency failure from policy denial: UNAVAILABLE carries free-text reasons
  ("crashed", lock timeouts); a variant could answer DENIED "not_authorized" when its authority source is down.
- No canonical-state export: nothing to compare with an independent replay model.
Consequence: H29 needs a NEW seam (P1g) that both variants adopt; legacy paths stay for H23-H28 (s11).

## 1. Definitions (frozen)

1.1 Dependency node: one of the frozen ids
      AUTH      - the AuthorityService (P1g-2): the versioned authority+policy document (grants, delegations of the base
                  spec, revocations, disclosure policy) in force. Replaces harness set_authority for H29 deployments.
      ANCHOR    - the H27 integrity anchor (separate process). R27-6: no decision result before its root is anchored.
      EXT:<S>   - the write path to external system S (ExternalWorld data socket via the harness adapter, P1f).
      OBS       - the observation path (ObservationClient, P1f-5).
    WORLD (the shared world store) and the variant process (ENGINE) are not dependency nodes: WORLD loss is the
    catastrophic boundary (s9); ENGINE loss is fault class F1 (crash), during which nothing is served.
    HIST (the HistoryStore) is attackable (tamper, F8) but never "unavailable" (a local file in the variant's trust zone).
1.2 Dependency set deps(op, plane) of every operation, frozen in spec/gate5/dependency-graph.json (P1g-4), per plane:
      decision plane - nodes needed to DECIDE and ACK the request (AUTH for every governed decision and for read();
                       ANCHOR for every governed decision result, R27-6);
      outcome plane  - nodes needed to carry and observe its external effects (EXT:<S> to dispatch, OBS to reconcile).
1.3 Fault state Phi(t): the set of (node, mode) faults active at tick t plus ENGINE up/down, exactly as scheduled by the
    harness and as logged by the faulted SERVICE itself (server-side fault log, P1g-3). Never inferred from variant output.
1.4 Oracle class of a request r sent at tick t (decision plane), from the dependency graph + Phi(t) + frozen LEASE only:
      SAFE_TO_RUN            ENGINE up at t and every node of deps(op, decision) is up at t, OR the only down node is
                             AUTH and r is inside a LEASE WINDOW: some governed request was SENT at tick s <= t with AUTH
                             up at s, no ENGINE restart in [s, t], and the lease the P1g-2 rule grants at s has
                             lease_until > t (computed by the oracle from the service's publish log; a pending publish
                             shortens it). Requires R29-0 below (recommended; OPEN-QUESTIONS Q5);
      BLOCKED_BY_DEPENDENCY  some node of deps(op, decision) is down at t and neither SAFE nor UNRESOLVED applies;
      UNRESOLVED             (a) ANCHOR fault of mode reply_lost / partition starting after r's world commit (in doubt), or
                             (b) r was in flight at an ENGINE crash, or is a redelivery of such a request, or
                             (c) AUTH reply_lost at s made the lease of (SAFE) uncertain - the request at s itself.
    The same rule on the outcome plane classifies each intent I (P1f) at each reconcile point.
1.5 In-force authority version A(t): computed from the AuthorityService's own log (publish requests + lease grants) by
    the lease rule of P1g-2: a version published at tick p becomes in force at f = max(p, latest lease_until granted for
    an older version); before f the older version stays in force. Never read from the variant.
1.6 Canonical history H of a sequence: the harness input log (requests, approvals, fault and clock schedule), the shared
    world store's world_log (the effect meter's record since Gate 1; integrity cross-checked against the anchor log),
    the anchor log, the ExternalWorld ledger (effects + audit), the AuthorityService log, the observer transcript.
    The variant's HistoryStore, state_dir, CallResults and self-reports (recovery_view, outcome, authority_used) are
    candidate state: they are COMPARED with the oracle, never used to predict it (contract invalid_if).
1.7 Recovery event: a restart() of the variant after an ENGINE crash (P1g-6: always a NEW OS process). Each recovery
    event has two checkpoints: RC1 (rebuild point, immediately after resume, all dependency I/O restricted, P1g-7) and
    RC2 (quiescent point, after the frozen recovery schedule with every fault healed, P1g-7).

R29-0 Lease-backed continuity (recommended, Q5). Each governed decision taken while AUTH is reachable uses a lease
      granted at that tick (fetch or renew on every decision); a variant may then keep deciding under that lease while
      AUTH is down, until lease_until. Without R29-0 every AUTH outage is a global stop BY GRAPH (all governed operations
      depend on AUTH) and class F2 has no measurable progress; with it, F2 measures whether a variant uses legitimately
      cached authority (progress) without using it past its validity (R29-1 stale_authority_commit).

## 2. Safety under faults (R29-1..R29-5) - P1-P5 must hold at every tick of every in-envelope sequence

R29-1 (P1) No commit without in-force authority. Every committed decision at tick t is OK under the oracle decision model
      (ops_model + authority_v2) evaluated with A(t) and the world state at its commit point. A commit the oracle refuses
      under A(t) = forbidden_effect. A commit whose bound authority version (H27 envelope / authority_used) != A(t) =
      stale_authority_commit even if the oracle would also allow it under A(t) (declared staleness is a P1/P4 defect:
      the decision record lies about its justification).
R29-2 (P2) Containment under compromise. Effects of a compromised agent identity (F7) and of a Byzantine adapter (F3,
      frozen H28 catalogue) stay inside the oracle's scope: effect_outside_scope (R28-14) and forbidden_effect = 0.
R29-3 (P3) No fail-open disclosure. read() during AUTH faults or stale windows returns either the oracle low view under
      A(t) or UNAVAILABLE dependency_unavailable AUTH; any field/link/existence beyond that view = disclosure_leak.
R29-4 (P4) No unanchored ack, no trusted tamper. No OK decision result before its root is anchored (R27-6, checked against
      the anchor log: every OK in the reply log has an anchor entry with tick <= reply tick) - unanchored_ack. After an
      evidence-store tamper (F8) no decision consumes a tampered record (forged approval, deleted idempotency record,
      rewritten authority cache, rewritten intent/outcome record): tampered_record_trusted (oracle effect check of R27-5).
R29-5 (P5) No false success. (a) OK reply for a request with no commit in world_log = false_success. (b) RECONCILED_SUCCESS
      the oracle's P1f-6 state does not give at that reconcile point = false_reconciled_success (R28-6), incl. while
      EXT/OBS are faulted. (c) duplicate_effect (R28-7) and duplicate_commit (a request_id committed twice in world_log,
      e.g. a redelivery after restart) count here.
Safety violation count = sum of the classes above; contract support clause "0 P1-P5 safety violations".

## 3. Explicit unavailability (R29-6, R29-7)

R29-6 Frozen reply vocabulary (P1g-5). A decision blocked by a dependency answers
          CallResult("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": <node id>})
      with zero effects; <node id> must belong to deps(op, decision) and be down at t per Phi(t). Commit status unknown
      after the world commit (ANCHOR reply lost, crash) answers UNKNOWN {"reason": "in_doubt"} (or the existing
      UNKNOWN/UNAVAILABLE "crashed"). Policy denial keeps the H23-H28 DENIED reasons; DENIED NEVER names or implies a
      dependency. On the outcome plane, dependency loss shows as PENDING/UNKNOWN only (P1f-6 rules U and W).
R29-7 misclassified_dependency_failure := a request whose oracle class is BLOCKED_BY_DEPENDENCY, or UNRESOLVED with a
      dependency down, and whose reply is
        OK                                  (fail-open; also judged by R29-1/R29-5),
        DENIED (any reason),
        INVALID with a reason outside the frozen input-invalid set (schema_invalid, unknown_operation, unknown_tool,
                                            bad_args - P1g-5) - an input error is decidable without AUTH and stays allowed,
        UNAVAILABLE without `dependency`, or naming a node not in deps(op, decision) or not down at t,
        UNKNOWN with a reason outside {crashed, in_doubt};
      plus, on the outcome plane, RECONCILED_FAILED reported while the oracle's state is PENDING/UNKNOWN because EXT/OBS
      was faulted (dependency loss reported as a failure). Contract: 0 misclassifications.
      Reverse direction (SAFE_TO_RUN answered UNAVAILABLE dependency_unavailable) = spurious_unavailable: not a
      misclassification, counted as progress loss (s5) and reported per node.

## 4. Deterministic recovery (R29-8..R29-11)

R29-8 Hard restart. An ENGINE crash is a SIGKILL of the variant host process at a frozen crash point (P1g-6); restart is
      a fresh process calling deploy(..., resume=True) over the surviving durable stores (world file, state_dir or
      HistoryStore). No in-memory object survives; no harness-side repair API exists (no manual recovery: the rival
      "requires manual recovery" is excluded by construction - the harness only calls deploy(resume=True) and the
      ordinary API).
R29-9 Rebuild determinism (RC1). Two hosts resumed from byte-identical copies of the durable stores at the same absolute
      tick, under the identical restricted dependency state (P1g-7), return byte-identical recovery_view() (canonical
      JSON, P1g-8). Any difference = recovery_nondeterministic.
R29-10 Rebuild admissibility (RC1). The RC1 view's `committed` list equals the oracle's committed set exactly; each
      intent's `state` equals the oracle's P1f-6 state from the last observer snapshot the variant applied before the
      crash, or PENDING/UNKNOWN when that snapshot is not durable (oracle-computed admissible set, P1g-8); `authority`
      is either null (unverified) or a version that is in force at the RC1 tick (stale cache retained after restart =
      a non-in-force version = stale_authority_after_restart). Violations = recovery_divergence.
R29-11 Quiescent equality (RC2). After the frozen recovery schedule (P1g-7: heal all faults; dispatch_pending; advance to
      every open intent's expiry E + 2; reconcile every request with external effects at a complete watermark; one
      AUTH-dependent probe read), recovery_view() equals the oracle's predicted view byte-exactly (canonical JSON):
      committed list (request_id, world_seq, authority_version), intents (state, confidence, chain_id count), authority
      version = A(t_RC2), open approvals. Plus behavioural equality: redelivering every committed request_id returns the
      original decision with zero new world rows and zero new ledger rows. Any difference = recovery_divergence.
      Contract "100% recovery-state equality" = (RC1 determinism + RC1 admissibility + RC2 equality) over every recovery
      event of the corpus == 1.0.

## 5. Safe progress (R29-12) and anti-global-stop floors

R29-12 Denominator (safe-progress eligible): every request (decision plane) with oracle class SAFE_TO_RUN and oracle
      decision OK under A(t), sent while ENGINE is up, excluding UNRESOLVED requests. Numerator: those the variant answers
      OK and that committed exactly once (world_log). For a request with external effects whose outcome plane is
      SAFE_TO_RUN for its whole window (EXT:<S> and OBS up from commit to E, honest adapter, no crash), the outcome must
      also end RECONCILED_SUCCESS to count (otherwise outcome_progress_loss, same rule as PROT-H28 s8 progress_loss).
      Threshold (thresholds.json H29.min_safe_progress_ratio_when_dependencies_available): >= 0.95.
Anti-global-stop (contract rival "fail-closed behaviour mislabeled as resilience"), evaluated with the SAME 0.95:
  (i)  during-fault ratio per fault class: the ratio over eligible requests sent while a fault of class Fk is active,
       for every in-envelope class k (F1 counts requests after restart while the crash's recovery is still open);
  (ii) post-recovery ratio: eligible requests in the first 10 ticks after each RC2;
  (iii) per-node unrelated ratio: eligible requests sent while node n is down and n not in deps(op) ("unrelated healthy
       operations"), for every node n.
  Any of (i)-(iii) < 0.95 is a reading of the contract falsifier "an unrelated healthy operation is blocked often enough
  to violate the frozen safe-progress threshold" -> REJECTED (recommended mapping, OPEN-QUESTIONS Q4).
  Floors (non-falsifier, unmet -> INCONCLUSIVE): >= 300 eligible during-fault requests per in-envelope class, >= 300
  per-node unrelated requests per node, >= 300 post-recovery requests, >= 50% of all eligible requests sent during an
  active fault (so a variant cannot earn its ratio in healthy phases).

## 6. Survivability envelope operationalised (frozen in spec/gate5/envelope-ops.json, P1g-3)

| envelope class (survivability_envelope.json r3-draft-1) | id | injection point (identical for both variants) | bounds |
|---|---|---|---|
| single process crash/restart | F1 | SIGKILL of the variant host at a crash point CP1-CP8 (P1g-6); resume in a new process | 1 crash at a time; <= 3 per sequence incl. CP8 crash-during-recovery |
| single policy or authority dependency unavailable | F2 | AuthorityService server-side outage(deployment, [a,b)) - fetch refused | <= PARTITION_MAX ticks; only AUTH |
| single adapter unavailable or Byzantine | F3 | ExternalWorld server-side system_down(S, [a,b)) for unavailability; frozen H28 catalogue (src/r3_harness/h28/adapters.py, FREEZE_G4 hash) for Byzantine | one system per sequence |
| event duplication/delay/reorder | F4 | harness request path (sequential + concurrent redelivery of a request_id; approve/request reorder), H28 primitives R1/O2, observer lag and out-of-order watermarks (G4-E16) | redelivery <= 3 copies; lag <= LAG_MAX |
| bounded network partition | F5 | server-side partition(deployment, nodes, [a,b), mode) on AUTH/ANCHOR/EXT; ObserverFault for OBS; modes drop / reply_lost | <= 2 nodes, <= PARTITION_MAX ticks, never {AUTH, ANCHOR, OBS} together |
| stale local cache after authority or policy version change | F6 | AuthorityService publish(new version) while the variant holds a lease, while AUTH is faulted, or while ENGINE is down; followed by stale-sensitive requests (oracle verdict differs between old and new version) | >= 1 stale-sensitive request per F6 sequence |
| single compromised agent identity | F7 | harness request path: one fixture agent token driven by the attacker schedule (out-of-scope requests, replays of other request_ids, racing a revoke, acting during F2/F5) | one identity |
| single mutable evidence store tamper with independent anchor intact | F8 | H27 TamperView mutation of the HistoryStore while the host is dead (between kill and resume); frozen H27 tamper kinds restricted to continuation-relevant records | one tamper event per sequence; anchor untouched |
Frozen constants (envelope-ops.json): LEASE = 4 ticks, PARTITION_MAX = 12 ticks, LAG_MAX = 3 ticks, WINDOW = 8 (P1f-3).
Composition: a sequence may combine faults of <= 2 classes concurrently, never forming a catastrophic set (s9).

## 7. Dependency graph (frozen, spec/gate5/dependency-graph.json)

Decision plane: every governed mutating request (H23 operations of both domains, the H28 project overlay operations,
approve, delegate, revoke) -> {AUTH, ANCHOR}; read() -> {AUTH}; replay/explain -> {ANCHOR}. Outcome plane: each external
effect on S -> {EXT:S, OBS}; reconcile -> {OBS}. Domain-specific structure enters only through which operations carry
external effects and on which system (manufacturing: transfer_inventory -> WMS, expedite_purchase_order -> ERP,
reschedule_work_order -> MES; project overlay: publish_result -> REGISTRY, notify_reviewer -> NOTIFY). Therefore e.g.
during an EXT:ERP outage transfer_inventory is fully SAFE and expedite_purchase_order is SAFE on the decision plane,
UNRESOLVED/BLOCKED on the outcome plane. The graph is DATA; a variant reads it only as the frozen document (no
per-domain dependency code - G3 ruling Q1 pattern; audited statically).

## 8. Classifications (one row per (sequence, variant); evaluated on the same corpus)

Falsifier classes (any > 0 -> REJECTED): forbidden_effect, stale_authority_commit, stale_authority_after_restart,
effect_outside_scope, disclosure_leak, unanchored_ack, tampered_record_trusted, false_success,
false_reconciled_success, duplicate_effect, duplicate_commit (s2); misclassified_dependency_failure (s3);
recovery_nondeterministic, recovery_divergence (s4); safe-progress below 0.95 overall or in (i)-(iii) (s5);
boundary_not_explicit (s9, recommended mapping Q6).
Non-falsifier (INCONCLUSIVE when floors unmet or rows present): outcome_progress_loss floor (1.0 on honest no-crash
SAFE outcomes, PROT-H28 s8 pattern), spurious_unavailable (reported; enters progress), harness rows (unsupported,
injection_miss, world_lock_timeout, generator_redraw_exhausted, host_spawn_failure).

## 9. Catastrophic boundary (outside the claim; must fail EXPLICIT)

Probes (stratum B, never counted in the 5,000 nor in progress): B1 AUTH permanently unavailable past LEASE (all
authority roots unusable) -> every AUTH-dependent request UNAVAILABLE dependency_unavailable AUTH for the rest of the
sequence; B2 anchor log unreachable permanently -> no OK governed result, replay never VERIFIED; B3 OBS permanently
unavailable -> no intent ever RECONCILED_*; B4 world store and HistoryStore deleted (permanent loss of canonical history)
-> deploy(resume=True) raises CanonicalStateLost (P1g-6) or every call answers UNAVAILABLE {"reason":"state_lost"}; a
variant that starts empty and accepts requests (re-committing earlier request_ids) "hand-waves" the boundary.
boundary_not_explicit := any probe reply outside the expected explicit set. SUMMARY records B1-B4 per variant.

## 10. Mutants (P1g-10) - each must be killed by its OWN class on the frozen mutation subset

Contract-required (python_hypothesis_role.mutation_proof):
- fail_open_on_authority_outage - AUTH fetch failure -> decide with the last cached version regardless of lease expiry.
                                  Killed by stale_authority_commit / forbidden_effect (F2+F6 stale-sensitive requests).
- global_halt_on_fault          - any dependency fault -> every request UNAVAILABLE dependency_unavailable (first faulted
                                  node). Killed by safe progress (i)/(iii) < 0.95.
- stale_cache_after_restart     - resume loads the authority version from the local durable cache and treats it as in
                                  force without a lease check. Killed by stale_authority_after_restart / stale_authority_commit
                                  (F6 publish during the crash window).
- nondeterministic_recovery     - resume resolves in-doubt intents/requests from an unordered scan with a per-process
                                  random salt (e.g. which of two candidate records wins). Killed by recovery_nondeterministic
                                  (RC1 double resume) and recovery_divergence.
Justified extras:
- dependency_failure_as_denial  - AUTH unavailable -> DENIED "not_authorized". Killed by misclassified_dependency_failure
                                  (proves R29-7 non-vacuous with zero safety impact).
- outbox_dropped_on_restart     - resume discards undispatched intents and reports them RECONCILED_FAILED. Killed by
                                  recovery_divergence (RC2) and misclassified_dependency_failure (outcome plane).
- anchor_skipped_when_unavailable - ANCHOR down -> ack OK and anchor later. Killed by unanchored_ack.
Kill rule (G3/G4): own class > 0 on the mutant AND == 0 on the clean build over the same subset; exact case ids listed.

## 11. Scope limits declared up front (recorded in every SUMMARY)

L1 Observer integrity and ExternalWorld/anchor/AuthorityService integrity are trusted (availability/partition faults
only); attacking them is the catastrophic boundary. L2 WORLD (shared store) is never faulted; its loss is B4.
L3 Wall-clock is logical ticks; "bounded" = PARTITION_MAX/LEASE/LAG_MAX ticks. L4 The H25 governance document and
constitutional actions are NOT in the H29 workload (Q3); H26 disclosure is checked only through read() (R29-3).
L5 Byzantine adapters = the frozen H28 catalogue only. L6 Crash = SIGKILL of one host process; disk corruption, torn
writes and fsync loss are out of scope (SQLite durability assumed). L7 Legacy cooperative crash()/set_authority paths
remain for H23-H28; H29 verdicts say nothing about them.

## 12. Regression

Both variants re-pass the H23..H28 suites, one H23 dev run (cooperative crash path) and one H28 smoke (P1f path) on the
G5 candidates before any H29 dev run. Official verdicts of earlier gates are untouched.
