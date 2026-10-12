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
