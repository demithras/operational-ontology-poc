# Gate 5 open questions - rulings needed before freezing PROT-H29 / P1g / ORACLE-AND-HARNESS-G5

Each with a recommended answer. "author" = needs the author; "orch" = orchestrator may rule. Drafted 2026-10-12 by the
g5 designer at HEAD d673a2c (read-only).

Q1 (author) Official attempt budget for Gate 5, declared before the first official run. Gate 3 used 3 (G3-E33), Gate 4
  declared 3 (Q1 2026-10-09) and used 1 (exp-h28-001 INVALID did not count, G4-E27). H29 is the most complex harness so
  far (new seams in both variants, process host, three services).
  RECOMMEND: at most THREE official attempts per variant (exp-h29-001..003), seeds 2921/2922/2923 declared in the freeze
  commit (dev 2911, smoke 2912); an attempt after a rejection needs ATTRIBUTION.md + a new candidate tag; the last attempt
  run is FINAL; a harness/launch-invalid run does not count and is repeated only by a new author decision on a NEW seed
  (G4-E27 precedent: the seen corpus is never reused).

Q2 (author) Envelope version. threat_model/survivability_envelope.json says "version": "r3-draft-1". The contract
  requires a frozen envelope and forbids narrowing/expanding it after failures.
  RECOMMEND: freeze the file byte-identical (no content change, the word "draft" stays in the version string - editing it
  would change the hash the contract binds) and record in the G5 author decision: "r3-draft-1 IS the frozen H29 envelope".
  All operational detail (injection points, LEASE=4, PARTITION_MAX=12, LAG_MAX=3, composition <= 2 classes, catastrophic
  sets) goes into a NEW file spec/gate5/envelope-ops.json ("r3-envelope-ops-1"), frozen in FREEZE_G5. Any later change to
  either file = a new envelope version and a new gate design, never an erratum. Alternative: bump to "r3-envelope-1" now
  (allowed: no H29 evidence exists) - cosmetically cleaner, but touches a threat-model file other gates reference.

Q3 (author) Workload scope. H29 workload = H23 operations of both domains + H28 project overlay + approve/delegate/revoke
  + read() (P3 probe) + external effects. The H25 governance document / constitutional actions are EXCLUDED (scope limit
  L4): including them adds a fourth dependency (governance document) and the H25 oracle to every sequence.
  RECOMMEND exclude, record L4. Alternative: add a POLICY node serving the governance doc (doubles F2 strata).

Q4 (author) Safe-progress reading. thresholds.json has one number (0.95). An aggregate-only ratio lets a variant that
  halts during faults pass on healthy-phase volume (rival "fail-closed mislabeled as resilience").
  RECOMMEND the 0.95 applies to the overall ratio AND to (i) every fault class's during-fault ratio, (ii) post-recovery
  ratio, (iii) every node's unrelated-operation ratio; any < 0.95 -> REJECTED (contract falsifier 2). Floors (>= 300 per
  class/node/post-recovery, >= 50% of eligible requests during faults) -> INCONCLUSIVE when unmet. Same pattern as the
  author's G2 2b / G3 Q3 / G4 Q7 floors.

Q5 (author) Lease-backed continuity (PROT-H29 R29-0). Every governed operation depends on AUTH, so without leases an
  AUTH outage is a global stop BY GRAPH and F2 progress is unmeasurable.
  RECOMMEND adopt R29-0: AuthorityService grants leases (LEASE = 4 ticks); variants renew on every decision while AUTH is
  up and may decide under a valid lease while it is down; the oracle classifies lease-window requests SAFE_TO_RUN (they
  must progress) and decisions past lease_until as stale (R29-1). Publishing a new version waits for outstanding leases
  (lease rule P1g-2), so honouring leases is always safe. Alternative: no leases; F2 judged on explicitness/staleness only
  and its (i) ratio reported "not applicable by graph".

Q6 (author) Catastrophic boundary handling. The contract scope says out-of-envelope loss "must fail explicit rather than
  be hand-waved as supported" but has no evaluator clause for it.
  RECOMMEND probes B1-B4 (>= 50 each, stratum S-bnd, not counted in the 5,000 or in progress); boundary_not_explicit > 0
  -> REJECTED (a hand-waved boundary is the claim the scope sentence forbids). Alternative: report only (weaker).

Q7 (orch) Hard crash. Cooperative crash() cannot detect a cache that survives "death" (mutant stale_cache_after_restart
  would be untestable). RECOMMEND every H29 crash = SIGKILL of a spawned variant host process at a shared crash point
  (P1g-3/P1g-6) and resume in a NEW process (deploy(resume=True)); cooperative crash() stays for H23-H28 only. Cost
  ~0.5-1 s per spawn (estimate ~3-4.5 h wall per official run, s13).

Q8 (orch) Mapping of "0 dependency failures misclassified" (support_if without a reject twin). RECOMMEND > 0 ->
  REJECTED (falsifier 4 of the contract names it; G3 Q5 / G4 Q6 precedent: every preregistered falsifier-level miss rejects).

Q9 (orch) INVALID reasons under AUTH outage. An input-invalid request (schema, unknown op) is decidable without AUTH.
  RECOMMEND frozen INPUT_INVALID_REASONS + spec/gate5/reason-map.json mapping each variant's existing INVALID reason
  strings to them (built from the H23 oracle's reason classes, reviewed by the equivalence auditor, frozen); INVALID with
  an unmapped reason while a dependency is down = misclassification. No free-text matching.

Q10 (orch) Canonical-state equality relation. RECOMMEND byte-exact canonical JSON (canon_json, G4-E1) of the frozen
  RECOVERY_VIEW at RC2, and byte-exact A/B equality at RC1; RC1 vs oracle is an admissible-SET check (in-doubt fields may
  legitimately be PENDING/UNKNOWN or authority null). Fields chosen to be ledger-determined so Paladin's
  never-resubmit and conventional's redeliver styles both have one exact oracle prediction (EQUIVALENCE E3).

Q11 (orch) World store as canonical history. The oracle uses world_log only to resolve commit status of UNRESOLVED
  requests and as the object of checks (anchor-cross-checked); SAFE requests are predicted independently.
  RECOMMEND accept; this is not "candidate state as its own oracle" because world_log is the shared effect record the
  meter has trusted since Gate 1 (written through the shared WorldHandle) and every OK commit is anchored (R27-6). Any
  world_log row without a matching anchor entry is itself a finding (unanchored_ack / world_divergence).

Q12 (orch) ExternalWorld refusal reason `unavailable` evaluated BEFORE bad_signature (a down system authenticates
  nothing) - an addition to the frozen P1f-2 order. RECOMMEND accept as P1g text (not a G4 erratum): G4 evidence never
  contains it, and the H28 smoke on the P1g commit must stay byte-identical (regression).

Q13 (orch) Fault composition. "single X" per class; RECOMMEND <= 2 concurrent classes from different components, never
  {AUTH, ANCHOR, OBS} down together, never two crashes overlapping (a crash during recovery CP8 is sequential). Frozen in
  envelope-ops.json.

Q14 (orch) Hypothesis use. RECOMMEND RuleBasedStateMachine for dev exploration + shrinking; the official corpus is a
  counted seeded list from the SAME frozen rule table (rules.py) (G4 Q14 pattern); a test asserts generator step kinds ==
  machine rules (set difference).

Q15 (orch) Equivalence audit points before dev1: lease cache is NOT shared code (E2); conventional must get per-
  dependency breakers + bulkheads + lease TTL (not fail-static); both read dependency-graph.json as data. RECOMMEND as
  EQUIVALENCE-G5; auditor rows in HARDENING_LEDGER.jsonl before dev1.

Q16 (orch) Freeze manifest. RECOMMEND exactly the ORACLE-AND-HARNESS-G5 s9 list, enforced by test_freeze_g5_manifest.py
  and by run_h29.py for non-dev ids; every evaluator is_dev branch mirrored as a launcher refusal (AST-enumerated test).
  (G4-E27 lesson; the H28 catalogue hash is re-listed because F3-byz reuses it.)

Q17 (orch) Upstream: H24, H27, H28 are SUPPORTED for both variants (G2, G4 exp-h28-001r). RECOMMEND no upstream stop; record
  the upstream verdict ids in the G5 freeze commit.

## Rulings (2026-10-12, before any Gate 5 implementation)
- Q1 (AUTHOR): at most THREE official attempts per variant (exp-h29-001..003), seeds 2921/2922/2923 declared now (dev 2911,
  smoke 2912). An attempt after a rejection needs ATTRIBUTION.md + a new candidate tag; the last attempt run is FINAL. A
  harness/launch-invalid run does not count and is repeated only by a new author decision on a NEW seed (G4-E27 precedent).
- Q2 (AUTHOR): threat_model/survivability_envelope.json ("r3-draft-1") is frozen byte-identical and IS the H29 envelope;
  operational detail goes into spec/gate5/envelope-ops.json ("r3-envelope-ops-1"), frozen in FREEZE_G5 when P1g delivers it.
  Any later change to either file = a new envelope version and a new gate design, never an erratum.
- Q3 (AUTHOR): H25 governance document / constitutional actions excluded from the H29 workload; scope limit L4.
- Q4 (AUTHOR): safe-progress 0.95 applies to the overall ratio AND to every fault class's during-fault ratio, the
  post-recovery ratio and every node's unrelated-operation ratio; any < 0.95 -> REJECTED. Floors as drafted -> INCONCLUSIVE.
- Q5 (AUTHOR): R29-0 lease-backed continuity adopted, LEASE = 4 ticks, H29 path only (authority_source given); the legacy
  set_authority path for H23-H28 is unchanged. Regression: H23-H28 suites + one H24 dev regression run on the G5 candidate.
- Q6 (AUTHOR): boundary probes B1-B4 (>= 50 each, outside the 5,000 and outside progress); boundary_not_explicit > 0 -> REJECTED.
- Q7-Q17 (orch): recommendations accepted as written. Q11 accepted with its condition: world_log only resolves the commit
  status of UNRESOLVED requests and every OK row must have a matching anchor entry (else a finding). Q16: every file of the
  ORACLE-AND-HARNESS-G5 freeze manifest that does not exist yet is added to FREEZE_G5 in the commit that creates it, before
  any dev run; the launcher refuses a non-dev id while any manifest file is missing from FREEZE_G5.

## Errata G5-E1..E9 (orch, 2026-10-12, from the P1g build report reports/p1g-report.md, before any Gate 5 variant/harness builder)
G5-E1 spec/gate5/authority-versions/<domain>/*.json (ORACLE-AND-HARNESS-G5 s9, F6-stale "narrowed doc"): built by the harness
      builder, not P1g. Content: for each domain, versions v1..vN each = the domain's version-0 authority spec with exactly ONE
      grant removed (narrowing only, never widening), generated deterministically by a harness script from the frozen auth
      specs; every file is added to FREEZE_G5 in the commit that creates it, before dev1.
G5-E2 The AuthorityService starts empty; the harness publishes version 0 at tick 0 for every deployment before the first
      request; fetch before any publish is an error (harness defect, never a variant finding).
G5-E3 Publish while an earlier publish is still pending: effective tick f_n = max(p_n, latest lease_until granted for any older
      digest, f_(n-1)); publish order = effect order. The oracle's in-force rule (PROT-H29 1.5) uses the same formula. The lease
      MAC covers (deployment, digest, granted_tick, lease_until).
G5-E4 ExternalWorld `unavailable` (checked before authentication, Q12) is decided from the request's system route and the
      fault plane; claims read from an unverified cap are NEVER used for attribution: the audit row of an `unavailable`
      refusal carries deployment null and the claimed caveats only under a separate key "unverified_claim". A forged cap
      during an outage gets `unavailable` instead of `bad_signature`; neither creates an effect. (P1g fix1.)
G5-E5 Crash keys: CP6 = request_id of the call that just returned; CP7 = request_id of the reconcile call; CP8 = "dispatch_pending"
      (first dispatch after resume). CP4/CP5 hooks belong to the harness adapter wrapper.
G5-E6 One fault-control form (schemas/fault-control.schema.json): {op outage|partition, deployment, [target], from_tick,
      to_tick, mode}; for the anchor, deployment = stream id.
G5-E7 Service connect failure (process gone) stays AnchorError/AuthorityError: every envelope outage/partition (F2, F3, F5) is
      server-signalled, and killing a service process is outside the envelope (envelope-ops.json classes). Only the
      server-signalled drop / closed-without-reply raise AnchorUnavailable / AuthorityUnavailable (DependencyUnavailable).
      ObserverUnavailable stays an outcome-level fault (H28 P1f-6 UNKNOWN), not a request reply.
G5-E8 The host builds adapters from deploy_spec "adapter_factory" = "module:function" (r3_shared cannot import r3_harness).
G5-E9 dependency-graph.json carries a top-level "systems" map (per-domain EXT node + OBS) so GEN-NULL = EXT:GEN-NULL with no OBS.

## Errata G5-E10..E15 (orch, 2026-10-12, from the G5 conventional + paladin build reports, before any dev run)
G5-E10 Bound authority version (R29-1 "authority_used", RECOVERY_VIEW committed[].authority_version, H27 envelope): the
      digest of the AuthorityService document in force (A(t), PROT-H29 1.5) under which the decision was taken, i.e. the
      leased digest. World-local delegate/revoke edges do NOT change it (they are world state checked by ops_model at the
      commit point, not authority versions). Oracle and both variants use this digest.
G5-E11 Canonical approval fingerprint (RECOVERY_VIEW approvals_open): sha256 hex of canon_json({"subject": requester,
      "on_behalf_of": on_behalf_of or null, "operation": operation, "inputs": args}) with r3_shared.extadapter.canon_json
      (G4-E1); one entry per unconsumed approval, de-duplicated, sorted. Oracle and both variants compute exactly this.
G5-E12 Commit in the world but not anchored (crash at CP2 / ANCHOR reply lost). Before RC2: a redelivery of that request_id
      may answer UNKNOWN {"reason": "in_doubt"} or UNAVAILABLE {"reason": "dependency_unavailable", "dependency": "ANCHOR"}
      while ANCHOR is down (both admissible under R29-7). At RC2 (all faults healed, P1g-7): the variant has completed the
      missing anchor entry (on resume, on the first call after heal, or on redelivery - the variant's choice), the commit's
      intents are dispatched like any committed intent at dispatch_pending, and redelivery returns the ORIGINAL decision
      with zero new world rows and zero new external-ledger rows (R29-11). A world row still unanchored at RC2 =
      unanchored_ack finding (Q11). A commit without request_id is anchored on resume or the first governed call after heal.
      Answering in_doubt for ever, or never dispatching a committed intent, = recovery_divergence.
G5-E13 Invalid/unknown token while a dependency of (op, decision) is down: the oracle class follows deps(op, decision) and Phi(t)
      like any request (BLOCKED_BY_DEPENDENCY), so the admissible reply is UNAVAILABLE {"dependency": <down node in deps>};
      DENIED would be a misclassification (R29-7). With all deps up, the H23-H28 DENIED/INVALID behaviour is unchanged.
G5-E14 INVALID while blocked: on the H29 path, an INVALID reply sent while any dependency of (op, decision) is down carries a
      reason from INPUT_INVALID_REASONS verbatim (P1g-5). spec/gate5/reason-map.json maps each variant's legacy INVALID reason
      strings (healthy path) to that set; it is built by the equivalence auditor from both variants' code and the H23 oracle
      reason classes, reviewed, and frozen in FREEZE_G5 before dev1.
G5-E15 A crash point never returns after SIGKILL (P1g fix2): faultplane._kill blocks the calling thread for ever after the
      signal, so nothing after the hook can run. Variant tests must NOT tolerate either side of the race (no retry/skip on a
      lost race): a crash point that is passed is a P1g defect, not a variant behaviour.
G5-E16 "Original decision" on redelivery (R29-11 behavioural equality; F4-dup "original decision repeated"): the decision-plane
      status, and for a non-OK status its reason; the reply body is NOT compared (after a lost acknowledgement the caller never
      received a body, and the body is not part of the decision). Body equality of redeliveries is reported descriptively per
      variant, never as a class. Applies identically to both variants and to the judge.

## Errata G5-E17..E24 (orch, 2026-10-12, from the G5 harness build report, before any dev run)
G5-E17 RC1 restricted dependency state (P1g-7) covers AUTH, EXT and OBS outages; there is no ANCHOR read-only control, so
      the RC1 "no append" rule for ANCHOR is checked by comparing the anchor head before/after RC1, not enforced by a fault.
G5-E18 After an ENGINE restart a variant MAY use a still-valid lease it can verify, but is not required to; a fresh fetch
      before the first governed decision is always admissible. The oracle's lease windows end at an ENGINE restart (PROT-H29
      1.4 "no ENGINE restart in [s, t]").
G5-E19 The judge applies R29-7 literally. Where a known-negative fake (ORACLE-AND-HARNESS-G5 s10) also produces
      misclassified_dependency_failure by R29-7's own definition (FakeFailOpenAuth, FakeStaleRestart, FakeAckBeforeAnchor),
      that class is added to the fake's expected set; s10 "EXACTLY its expected class set" then holds with the extended set.
G5-E20 The anchor log carries no tick; the "anchor entry tick <= reply tick" check is replaced by ordering: the anchor
      entry's sequence must precede the variant's reply in the harness transcript (same absolute clock step).
G5-E21 AUTH governs every governed operation, so its per-node unrelated-operation floor (Q4 (iii)) is "not applicable by
      graph" and reported as such; ANCHOR, EXT:* and OBS keep the floor.
G5-E22 spec/gate5/reason-map.json form: {"form": "r3-reason-map-1", "variants": {<variant>: {<raw INVALID reason>:
      <one of INPUT_INVALID_REASONS>}}}; built by the equivalence auditor from both variants and the H23 oracle reason
      classes; an unmapped raw reason while blocked = misclassification (G5-E14).
G5-E23 OBS outage (F5 on OBS) is injected by making the observer's ledger source unavailable to the shared ObservationClient
      for the window (the real observation path); the observer itself is not attacked (L1 from G4 stays).
G5-E24 Boundary probes: B1-B4 each >= 50 (author Q6). B2 (anchor permanently unreachable: permanent anchor outage) must be
      implemented and judged (no OK governed result, replay never VERIFIED). B4: the shared host (r3_shared/host.py) refuses
      resume over absent durable stores with CanonicalStateLost before the variant runs; this is part of the deployed system
      of BOTH variants, so B4 is explicit by shared construction and NOT variant-discriminating; SUMMARY must say so.
      FakeEmptyOnLoss stays a record-level judge test proving boundary_not_explicit is detected.

## Errata G5-E25..E27 (orch, 2026-10-12, from the G5 harness fix1 report, before any dev run)
G5-E25 Restricted-phase I/O is a recovery_divergence (R29-10). P1g-2 forbids a resumed deployment to append to the anchor,
      fetch a lease, write ExternalWorld or read the observer before the first API call after recovery_view(). Every
      restricted_io item the judge records (anchor head advanced across RC1 per G5-E17; an AuthorityService, ExternalWorld
      or observer request by the resumed deployment) is added to recovery_divergence with what="restricted_io". The
      restricted window is bounded by TRANSCRIPT ORDER (as G5-E20), not by tick: from resume until the harness's first call
      other than recovery_view(); a request issued after that call at the same tick is NOT restricted_io (G5-E18 allows a
      fresh fetch before the first governed decision). Same rule for both variants; conformance C29-5b stays the
      pre-dev-run encoding and must pass for both before dev1.
G5-E26 Known-negative fake sets (s10) under R29-7 literal, extending G5-E19: FakeFailOpenAuth = {stale_authority_commit,
      forbidden_effect, misclassified_dependency_failure, disclosure_leak, recovery_divergence}; FakeStaleRestart = the same
      plus stale_authority_after_restart (serving/committing past the lease also leaks reads and diverges the committed set).
      FakeDropOutbox = {recovery_divergence}: R29-7's outcome-plane clause requires RECONCILED_FAILED while EXT/OBS was
      faulted, and the fake drops intents on an ENGINE crash only. The outcome-plane branch must instead be proven non-vacuous
      by a record-level known-negative test (RECONCILED_FAILED while the oracle state is PENDING/UNKNOWN under an EXT or OBS
      fault -> misclassified_dependency_failure; same report without the fault -> not misclassified). Mutant
      outbox_dropped_on_restart is killed by recovery_divergence (kill rule: own class > 0 on the mutant, == 0 clean).
G5-E27 Oracle form comparison: recoverymodel.world_digest compares Verdict reason / derivation_hash by form (ops_model
      LOOSE_PROPS: non-blank / 64 hex), as every earlier gate's world comparison does; refused/unavailable ExternalWorld
      audit rows (G5-E4) are placed by the cap's claimed deployment for injection-effectiveness counting only, never as
      attribution evidence. Both are harness corrections, not design changes.

## Erratum G5-E28 (orch, 2026-10-12, from the G5 equivalence audit at e00fcec, before any dev run)
G5-E28 Input-invalid probes (Q9, G5-E14, R29-7 INVALID branch) must be exercised, and judged by the variants' own strict rule.
      (a) Corpus: rules.py gets an input-invalid probe step drawn from the SAME frozen rule table for every sequence, in healthy
          phases and inside every fault window; probe shapes: missing required input, unknown extra key, wrong-typed argument,
          unknown operation name, unknown tool name (one shape per probe, seeded). Probes carry invalid_probe=true through
          generation, transcript, judge AND finalize (judge_fin must not hard-code invalid_probe=False). Coverage floor: >= 50
          probes inside fault windows of AUTH or ANCHOR in an official run, else INCONCLUSIVE (floor pattern of Q4); per-shape
          counts reported.
      (b) Judge predicate: "input-invalid" = the strict frozen input schema (ops_model.schema_valid_args: unknown keys rejected,
          types checked) plus the P1g-5 envelope checks (request_id / on_behalf_of form), not ops_model.validate_args. For an
          input-invalid request the admissible replies are INVALID with a reason whose reason-map image is in
          INPUT_INVALID_REASONS (any member; the member is not compared), or UNAVAILABLE naming a node in deps(op) that is down.
      (c) Lease windows (R29-0): a send renews the lease in the oracle when it is AUTH-dependent with AUTH up, EXCEPT an
          input-invalid probe, which is decidable without AUTH. A variant may still fetch a lease while handling a probe (both
          currently do); such a lease is server-granted and honouring it is safe (P1g-2). Therefore: the obligation window
          (SAFE_TO_RUN, counted in progress) is computed WITHOUT probe sends; the admissibility window (a decision under a valid
          lease is not stale) is computed WITH them. A request inside the admissibility window but outside the obligation
          window may be decided under the lease or answered UNAVAILABLE AUTH; it is excluded from the progress denominators and
          reported as count lease_gap per variant.
      (d) An unknown operation or tool name is an input error decidable without dependencies: while any dependency of the
          request is down, the reply is INVALID unknown_operation / unknown_tool (or the variant's raw reason mapped to them),
          never UNKNOWN. With all dependencies up the legacy H23 reply is unchanged. Applies to both variants (conventional
          already complies; Paladin answered UNKNOWN - audit note N1).
      (e) spec/gate5/reason-map.json is produced by the equivalence auditor AFTER the variant fixes for (d) and frozen with the
          G5 manifest; new conformance C29-8: for every probe shape, under AUTH down and ANCHOR down, both variants' replies are
          admissible by (b) - must pass for both before dev1.

## Erratum G5-E29 (orch, 2026-10-13, from the G5 re-audit at 4646a3c, before any dev run)
G5-E29 (a) G5-E28(b)/(d) apply to requests the oracle classifies BLOCKED or UNRESOLVED (a dependency down and not covered by an
      admissibility lease), which is the scope R29-7 is judged on. Under a valid lease (SAFE_TO_RUN or lease_gap) the request is
      decided as with all dependencies up, and the legacy reply for an unknown name stands for both variants (audit N14).
      (b) The G5-E28(a) floor of >= 50 probes inside AUTH or ANCHOR fault windows counts the main corpus only; boundary-stratum
      (S-bnd, B1-B4) probes are reported separately and never count toward it (PROT-H29 s9 keeps stratum B out of main counts;
      audit N16).
      (c) Scope limit L5: schema-shape probes (missing input, unknown key, wrong type) use the direct surface; call_tool schema
      probes are not generated. Both variants gate call_tool before the tool binding (audit N15).
      (d) spec/gate5/reason-map.json is the equivalence auditor's map at 4646a3c (paladin 8 mapped, conventional 15 mapped;
      evidence spec/gate5/audit/mapping-table.md, findings.md); HARDENING_LEDGER.jsonl gains the 28 G5 rows (all present).

## Erratum G5-E30 (orch, 2026-10-13, from the read-only diagnosis of dev run exp-h29-dev1, before any official run)
G5-E30 (a) Input-invalid probes (G5-E28) are never eligible for progress: judge_req's eligibility rule excludes every request whose
      args fail the strict input predicate of G5-E28(b) (as G5-E28(c) already does for lease windows). In dev1 all 56 non-progressed
      eligible requests of both variants were unknown_key probes the oracle's lenient decide called OK; both variants answered
      INVALID correctly.
      (b) The crash-armed request (the step that arms a crash point) is excluded from eligibility and from the fault-share floor by
      the CORPUS (the step's armed flag), never by the variant's reply: sample-size floors must be variant-independent.
      (c) The generator guarantees the during-fault share: eligible requests sent during an active fault >= 55% of eligible
      requests (the frozen evaluator floor stays 50%; the margin is a generator property, asserted by a generator-only test over
      seeds 2911/2912/2921-2923 at full size).
      (d) F6 sequences: a sequence counts as F6-stale-sensitive only when a truly stale-sensitive request is EMITTED; the generator
      redraws the sequence's stale pair deterministically (same seed stream) when the crash request consumed it, and the counter
      is incremented only on emission. Generator-only test at full size over the same seeds: 0 F6 sequences without one.
      (e) Anchor evidence is indexed per anchor instance (worker i): (i, stream, decision_id). Each sequence is judged against the
      anchor of the worker that ran it. Stream names need only be unique within one anchor (both variants check that); merging
      anchors of independent workers is a harness defect (dev1: 58 of Paladin's 59 unanchored_ack vanish under a per-anchor index;
      the 59th is to be explained by the harness fix). Evidence keeps per-class detail rows (request id, tick, reason) for every
      class hit, not only counts, so SUMMARY attribution can cite cases.

## Erratum G5-E31 (orch, 2026-10-13, from the G5 fix4 paladin report (dev run exp-h29-dev2), before any official run)
G5-E31 The unanchored_ack ordering check (G5-E20) must not depend on the anchor service being reachable. The harness reads BOTH
      anchor_head_before and anchor_head_at_reply from the anchor's own append-only log file (as anchor_head_before already does),
      never through the anchor service, so an OK reply given while ANCHOR is dropped or partitioned is ordered against the entries
      that existed at the reply. An unreadable head after an OK reply is a harness row (blocking: the run cannot be clean), never
      "nothing to order against" (judge_req._anchor_entry_violation skipped it: an ack before anchoring during an ANCHOR outage,
      completed after heal by the same incarnation, was invisible in either variant). The frozen mutant definition stands as written
      ("ANCHOR down -> ack OK and anchor later"): the anchor-later step may happen after heal in the same incarnation, and the judge
      must kill it there.

## Erratum G5-E32 (orch + author decision, 2026-10-13, after official exp-h29-001)
G5-E32 The read judge (P3 / R29-3, judge_req._read) compares a served object with the oracle's low-view object under the same
      ops_model.LOOSE_PROPS rule as every world comparison (G5-E27): Verdict reason compared as non-blank, derivation_hash as 64
      lowercase hex; every other prop and the object set exactly. Applies to get and list reads, both variants. exp-h29-001
      (seed 2921, candidate r3-g5-cand2) was judged with a raw body equality and gave disclosure_leak=2 for both variants on
      Verdict reads whose value equals the oracle and whose only differences are those two loose props (ATTRIBUTION.md).
      AUTHOR DECISION (2026-10-13): exp-h29-001 is harness-INVALID and does not count as an attempt; its evidence stays
      committed unchanged. It is repeated once as exp-h29-001r on the NEW seed 2924 on a new candidate tag (the seen corpus is
      never reused, G4-E27 precedent). Seeds 2922 and 2923 remain reserved for attempts 2 and 3.

## Erratum G5-E33 (author decision 2026-10-13, Q11 strengthened; before the repeat of the official run)
G5-E33 Q11 is kept (the oracle learns which requests committed from the shared world store's world_log) and its stated
      condition "integrity cross-checked against the anchor log" (PROT-H29 1.6) is made complete and binding. The judge checked
      only OK reply -> anchor entry (judge_req unanchored_ack). Added, for both variants, evaluated at the end of every sequence
      (after RC2, so G5-E12 completion of unanchored commits has happened):
      (a) commit mark -> anchor: every world_log commit mark (kind=mark, ref=commit) has an anchor entry on that sequence's own
          anchor (G5-E30e) whose decision_id equals the mark's request_id (or, for a commit without request_id, the decision the
          variant anchored for that world_seq); a commit mark with no such entry -> recovery_divergence what="unanchored_commit".
      (b) anchor -> commit mark: every anchor entry recording an OK governed mutation has a world_log commit mark for the same
          request; an anchored OK decision with no commit mark -> recovery_divergence what="anchored_without_commit".
      (c) commit mark <-> ExternalWorld: every ExternalWorld effect row whose claimed deployment is the sequence's deployment
          belongs to a request with a commit mark (else forbidden_effect, as today); every commit mark whose oracle decision has
          external effects has, after RC2 dispatch_pending + reconcile, its effects in the ExternalWorld ledger, or a terminal
          RECONCILED_FAILED / in-doubt state the oracle admits (else recovery_divergence what="committed_effect_missing").
      (d) world_log integrity: seq strictly increasing without gaps and rows never rewritten between the harness's reads (the
          harness hashes the world_log prefix it has already read at each RC1 and at sequence end; a changed prefix ->
          recovery_divergence what="world_log_rewritten").
      Known-negative fakes/records prove each check (forged commit mark, deleted anchor entry, effect without commit, rewritten
      prefix) and both real variants stay clean at dev size. The world store remains the only variant-process file the oracle
      reads; this is stated in the SUMMARY.
