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
