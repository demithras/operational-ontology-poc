# Gate 4 open questions - rulings needed before freezing PROT-H28 / P1f / ORACLE-AND-HARNESS-G4

Each with a recommended answer. "author" = needs the author; "orch" = orchestrator may rule. Drafted 2026-10-09 by the
g4 designer at HEAD d055679 (read-only).

Q1 (author) Official attempt budget for Gate 4, declared before the first official run. Gate 3 used 3 attempts per
  hypothesis (exp-*-001/-002 rejected on variant/harness defects, -003 declared final only before it ran, G3-E33).
  RECOMMEND: at most 2 official attempts per variant (exp-h28-001, exp-h28-002), declared in the G4 freeze commit;
  -002 only after a written ATTRIBUTION.md of -001 and a new candidate tag; -002 is FINAL. A run made INVALID by a
  harness/launch fault (not a variant defect) may be repeated only by a new author decision and does not count. The
  Gate 4 SUMMARY reports attempts and every attributed rejection per variant.

Q2 (author) Project domain has NO external effect (spec/ops/project.json); the contract scope says "both public
  domains plus generated adapters". RECOMMEND an H28-only ops OVERLAY spec/ops/project.h28.json adding two operations
  with external effects (publish_result -> REGISTRY at_most_once/full; notify_reviewer -> NOTIFY idempotent_set/
  effects_only), with authority rules in a v3 auth overlay, frozen in FREEZE_G4; base specs untouched so H23-H27 are
  unaffected. Alternative: manufacturing + generated systems only, recorded as scope limit L6 (weaker; the domain-
  independence claim of H28 would rest on one domain).

Q3 (author) Lower-confidence classes under the stop rule. RECOMMEND frozen observability per system: WMS full, ERP
  full, MES effects_only (audit not visible -> refused substitutions invisible), plus one generated `none` system per
  domain (GEN-NULL) whose effects must stay UNKNOWN/low for ever. This makes the stop rule tested, not just declared.
  Effects_only/none systems are excluded from the "100% target mutations detected" denominator and reported apart.

Q4 (author) Outcome function shared or per-variant? Sharing removes noise but makes the core protection shared code
  (both pass/fail together; H26 Q4 precedent). RECOMMEND not shared: only P1f forms/vocabulary, caps crypto,
  ExternalWorld and ObservationClient are shared; each variant implements P1f-6; conformance C28-2 before dev runs.

Q5 (author) Observer = truth source; its integrity is not attacked (only unavailable/lagging faults). RECOMMEND accept
  as scope limit L1: attacking the observer too would be "global compromise of every independent trust root"
  (threat_model out-of-scope list). The independence check (shared_trust_root) still guards the rival "observation is
  not truly independent".

Q6 (orch) Mapping of "100% target mutations detected" (a support_if clause without a falsifier twin). RECOMMEND
  detection < 1.0 -> REJECTED (it is the falsifier "adapter lies about outcome/target"; consistent with G3 ruling Q5:
  any preregistered falsifier-level miss rejects), with attempted >= 300 as a floor (else INCONCLUSIVE).

Q7 (author) Non-falsifier floors (not in thresholds.json; PROT-H28 s8): outcome equality 1.0 at every reconcile
  point, honest progress 1.0, per-primitive >= 300, per (domain, system) >= 300, crash >= 200, none-class >= 300,
  observer-fault >= 300, honest controls >= 1,000. RECOMMEND as written; same pattern as G2 ruling 2b / G3 Q3/Q6:
  without them an always-UNKNOWN variant passes every falsifier clause.

Q8 (orch) Seam change scope. H28 moves external effects OUT of the world transaction (outbox + adapter after commit)
  when `external` is given; the legacy in-transaction path stays for H23-H27. RECOMMEND yes, plus the regression rule
  of G3 Q9 (H23-H27 suites + one H23 dev run with external=None on the G4 candidates; earlier verdicts untouched).

Q9 (orch) ExternalWorld as a separate OS process with its own key, outside the sandbox (H27 anchor pattern, G2
  decision a). RECOMMEND yes; in-process would let harness/variant code write the ledger and make the oracle
  "candidate-readable truth". The runner refuses non-dev ids without it (G3-E31b).

Q10 (orch) policy_gate_in_adapter target rule. RECOMMEND manufacturing approval rule
  `expedite-large-fee-needs-approval` (an authority/policy rule on an external operation) plus its project overlay
  analogue if Q2 is accepted; mutant moves it to adapter-side code.

Q11 (orch) Crash recovery styles differ (Paladin: never re-call adapter after crash -> UNKNOWN until observer
  decides; conventional: outbox redelivery with the same cap). RECOMMEND both legitimate under R28-8; progress floor
  computed on non-crash honest cases only; crash cases judged on duplicate_effect + outcome equality (EQUIVALENCE).

Q12 (orch) Follow-up probes for G2 (authority artefacts in replies) need a second request in the same case.
  RECOMMEND 2-request cases for G1/G2 only; the twin keeps the identical 2-request schedule.

Q13 (orch) Envelope byte-exactness ("byte-exact provenance envelope"): H28 cases run with HistoryStore + anchor (like
  H26 ruling Q10) so ExternalRequest.envelope_text is the real H27 envelope; recorder checks envelope_text equals
  the auditor envelope of the decision. RECOMMEND yes (adds cost; otherwise the mechanism clause is untested).

Q14 (orch) Hypothesis library use: derandomized strategies (database=None) for corpus draws + shrinking on dev replay
  only. RECOMMEND yes; the official corpus stays a counted, seeded list (reproducible), never adaptively generated.

Q15 (orch) Static audit resolution file spec/gate4/ADAPTER-AUDIT-RESOLUTIONS.json reviewed by the equivalence auditor
  BEFORE the official run, frozen with the candidate (G3-E24/E29 pattern). RECOMMEND yes; behavioural checks remain
  primary and no resolution can excuse a behavioural difference.

## Rulings (2026-10-09, before any Gate 4 implementation)
- Q1 (AUTHOR): at most THREE official attempts per variant for Gate 4 (exp-h28-001..003), declared now, before any run.
  An attempt after a rejection needs a written ATTRIBUTION.md of the previous one and a new candidate tag; exp-h28-003 (or the
  last attempt run) is FINAL. A run made invalid by a harness/launch fault (not a variant defect) does not count and is
  repeated only by a new author decision. The Gate 4 SUMMARY reports attempts and every attributed rejection per variant.
- Q2 (AUTHOR): accepted as recommended - H28-only overlay spec/ops/project.h28.json (publish_result, notify_reviewer) with a
  v3 auth overlay, frozen in FREEZE_G4; base specs untouched.
- Q3 (AUTHOR): accepted - frozen observability per system (WMS full, ERP full, MES effects_only) plus one generated `none`
  system per domain whose effects must stay UNKNOWN; reported apart from the target-mutation denominator.
- Q4 (orch, by the author's Gate 3 precedent "no shared visibility helper"): outcome function NOT shared; each variant
  implements P1f-6; conformance C28-2 before dev runs.
- Q5 (AUTHOR): accepted as scope limit L1 - the observer is not attacked (only unavailable/lagging); the independence check
  (shared_trust_root) stays.
- Q6-Q15 (orch): recommendations accepted as written. Q7 floors accepted as written (author precedent G2 2b / G3 Q3, Q6).

## Errata G4-E1..E14 (orch, 2026-10-09, from the P1f build report, before any Gate 4 variant/harness builder)
G4-E1 Canonical JSON for P1f forms = the anchor canon (sort_keys, compact separators, ensure_ascii=False), implemented once
      as r3_shared.extadapter.canon_json (P1f-3's `r3_shared.serial` does not exist).
G4-E2 spec/external/{manufacturing,project}.systems.json are frozen deliverables of P1f (added to FREEZE_G4).
G4-E3 GEN-NULL: one generated system per domain with a single operation `record` (at_most_once, target gen:<key>, semantics
      gen_record), observability `none`; the H28 harness synthesises these effects; every one must stay UNKNOWN (Q3 ruling).
G4-E4 Q2 overlay content as built in P1f is FROZEN: spec/ops/project.h28.json (publish_result: Verdict + visibility, rule
      publish-public-needs-approval; notify_reviewer: Hypothesis + reviewer) and spec/authority/project.h28.v3.json (grants h28-*);
      base ops byte-identical. publish-public-needs-approval is the project analogue for the policy_gate_in_adapter mutant (Q10).
G4-E5 credential_scope_broadened mutant: the minted cap keeps its correlation caveat but drops the target and payload-digest
      binding (system + op + correlation), so out-of-scope effects are ACCEPTED by ExternalWorld and measured, not refused.
G4-E6 Outcome `evidence` = sorted list of namespaced strings "E:<effects.seq>" / "A:<audit.seq>"; informational only; outcome
      equality (oracle vs variant) compares state and confidence, never evidence.
G4-E7 Rule U keeps the previous state's evidence; D1 evidence = the conflicting ledger rows; D3 applies to at_most_once AND
      exactly_once_required (PROT-H28 s4).
G4-E8 complete_through_tick = min(watermark - k, server_tick); a watermark ahead of the server never overstates completeness.
G4-E9 Refused rows: bad_signature rows are unattributed (deployment/chain/correlation empty) and invisible to observers;
      unknown_root and later refusal reasons carry the authenticated caveats; several distinct correlation caveats ->
      correlation_missing.
G4-E10 Ledger rows carry a `deployment` column; observation keys are scoped per deployment (HMAC(root_key, deployment), stored
      hashed); one ExternalWorld serves many per-case deployments.
G4-E11 Control-plane isolation is by construction (separate data and .ctl sockets, per-plane op allow-lists,
      ExternalClient.data_only()); the sandbox denies writes to the ext dir. Scope note: Byzantine adapters are harness-injected
      code; attacking the control socket is not an H28 attack class.
G4-E12 Identical caveat sets give an identical chain_id (re-minting cannot bypass max_uses); idempotency_disabled works only by
      changing caveats.
G4-E13 The ledger runs in WAL mode while live; close() switches to journal_mode=DELETE so a closed ledger is readable.
G4-E14 ExternalRequest validates shape on construction; the strict check (never a root cap; correlation == request_id#effect_index)
      is validate_request(strict_cap=True), used by the recorder and C28-3. Launcher env contract: R3_EXT_SOCK, R3_EXT_CTL
      (= R3_EXT_SOCK + ".ctl"), R3_EXT_DIR; require_external(exp_id) refuses non-dev ids without them.

## Errata G4-E15..E18 (orch, 2026-10-09, from the conventional G4 build report, before integration)
G4-E15 SUPERSEDES G4-E6 (which contradicted the frozen schema / validate_outcome and C28-2): outcome `evidence` = the sorted
      unique list of effect-ledger `effects.seq` values (positive ints) the state relies on; audit-ledger seqs are never in
      evidence. Evidence IS compared with the oracle in C28-2 as frozen. G4-E7 reads accordingly: D1 evidence = the conflicting
      effects rows; U keeps the previous evidence.
G4-E16 Outcome state is monotone in observation: a snapshot whose watermark is lower than one already applied is ignored (the
      previous state and evidence stay); a reconciled state never returns to PENDING.
G4-E17 A commit without a request_id uses the deterministic correlation base `anon-tx<world_seq>` (world_seq of its commit).
G4-E18 Envelope byte-exactness (Q13) is measured on non-crash cases only; crash cases are judged on duplicate_effect and outcome
      equality (Q11). A redelivered request after a crash-after-commit may carry envelope_text "" and is not counted as a
      provenance violation.
G4-E19 SUPERSEDES G4-E15 (which contradicted P1f-6 line "evidence = seqs of M (and of A when O == full)"): `evidence` is exactly
      as frozen in P1f-6 - a sorted list of positive ints: the effects.seq values of the matching effect rows M, plus the
      audit.seq values of the matching audit rows A when the system's observability O == full; duplicates are kept (the two
      seq namespaces are not distinguished; oracle and variants compute the identical list); compared with the oracle in C28-2.
      G4-E7 reads: D1 evidence = the conflicting rows by the same rule; U keeps the previous evidence. G4-E6 and G4-E15 are void.
