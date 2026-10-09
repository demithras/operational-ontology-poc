# Gate 3 open questions - rulings needed before freezing PROT-H25 / PROT-H26 / P1e

Each with a recommended answer. "author" = needs the author; "orch" = orchestrator may rule.

Q1 (author) Conventional baseline and the domain-branch clause. The H25 contract's baseline says "conventional policy
  engine with ... domain policy modules", while support requires 0 domain-specific privilege branches and DUAL_TRACK
  applies one evaluator to both. RECOMMEND: policy modules expressed as DATA (the shared governance document or a
  deterministic translation of it) are allowed for both; per-domain/per-model decision CODE counts as domain_branch for
  both. Otherwise the conventional verdict is REJECTED by construction (strawman by rule).

Q2 (author) "Structurally distinct" governance models. Contract says >= 3 without a definition. RECOMMEND the P1e-1
  signature rule (distinct in >= 2 of decision_rules, hierarchy, concurrence, precedence) with the three fixtures
  hierarchical / collegial / polycentric, frozen as files before any builder starts.

Q3 (author) H25 safe-progress and coverage floors (not in thresholds.json). RECOMMEND PROT-H25 s7: legit progress 1.0;
  per-model coverage of every reachable outcome rule and refusal class; >= 1,000 oracle_needed and >= 500 precedence
  cases; >= 1,000 race cases; unmet -> INCONCLUSIVE. Same pattern as the G2 ruling 2b.

Q4 (author) Shared visibility helper? Sharing `low_view`-like code with variants removes implementation-quality noise but
  makes sovereignty largely shared code (both variants pass/fail together; the mechanism claim "derived from the
  authority contract" is then untested per variant). RECOMMEND not shared: only forms and tool_schema are shared;
  C26-4 conformance catches semantic disagreements early (the E-9 lesson).

Q5 (orch) H25 reject mapping. reject_if omits emergency violations; falsifier 4 names them. RECOMMEND any preregistered
  falsifier -> REJECTED (emergency_violation > 0, illegitimate_effect > 0), consistent with G2 Q3.

Q6 (author) H26 floors (PROT-H26 s9): per-fact-kind >= 300 pairs, per-channel >= 500, >= 1,000 identifier probes,
  A/A >= 500 with 0 divergences, D4 replacement <= 50%, read correctness 1.0, exact tool exposure, 0 over-redaction.
  RECOMMEND as written; the anti-masquerade floors stop a deny-everything variant from passing noninterference.

Q7 (author) Declared low facts (PROT-H26 D1-D4). Each is an explicit allowed disclosure frozen BEFORE results (contract
  allows "explicit allowed-disclosure rules"). D2 (activity volume: seq/tick counters) is the weakest point: a real
  attacker can learn how much hidden activity happened. RECOMMEND accept D2 for Round 3, generate pairs with equal
  schedules, and record "activity volume is not protected" as a scope limit in the H26 SUMMARY; protecting it needs
  per-principal sequence spaces (a later hypothesis). D4 (outcome of authorised writes) likewise recorded.

Q8 (author) Chain fields in provenance views. Roots/prev/seq transitively cover hidden decisions; exposing them leaks
  (digests differ across pairs). RECOMMEND auditor-only (never in principal views); principal views are partial by
  definition. Consequence: no principal-verifiable redacted chain in Round 3 (needs Merkle/selective-disclosure
  commitments; later hypothesis). Recorded as a scope limit.

Q9 (orch) Check order for mutating calls (PROT-H26 3.2) supersedes E-10's freedom for Gate 3 candidates. Both variants
  must re-pass the H23 suite, one H23 dev run and the H24/H27 suites as regression (like G2 Q9/Q11); H23/H24/H27
  official verdicts untouched. RECOMMEND yes; reason strings of PROT-H24 for hidden parents/edges change to
  unknown_parent/unknown_edge (H24 evaluator treats reasons as informational, so its verdict logic is unaffected).

Q10 (orch) H26 deployments use history + anchor (provenance views need envelopes) under the sandbox runner, exactly as
  H27. RECOMMEND yes; replay/explain remain auditor-only and out of H26 scope (Q8).

Q11 (orch) Extra mutants: H25 `domain_privilege_branch` (proves the audit non-vacuous), H26 `subscription_unfiltered`
  and `redaction_fabrication` (prove the event and false-provenance checkers). RECOMMEND add (kill rate still 1.0).

Q12 (orch) The legacy `read(token, op, args)` is a token-bearing supported method, so it is IN H26 scope. RECOMMEND
  redefine it onto the P1e-5 forms in the P1e commit and update H23 tests that read bodies (H23 verdicts never used
  read bodies). Removing it instead would be "post-design scope surgery" on a supported channel.

Q13 (author) H25 cases inside H26: case visibility (s1.3) is in H26 scope via constitutional refusals on hidden cases,
  but there is no principal-facing case-status read. RECOMMEND keep it that way for Gate 3 (no case_view API); add one
  only with a new freeze.

Q14 (orch) Grandfathering on set_governance (PROT-H25 3.6): open cases are re-evaluated under the new document (no
  grandfathering). Alternative: freeze the document per case at propose. RECOMMEND no grandfathering (one rule, matches
  set_authority semantics in H23/H24); the generator covers mid-case changes so both variants are tested on it.

Q15 (orch) Volume/time budget. H25 10,000 cases x 2 variants + 1,000 renamed + 2,000 boundary re-runs; H26 5,000 pairs
  = 10,000+ deployments per variant plus 20,000 fuzz calls. RECOMMEND parallel official runs (G2 lesson 6) and a smoke
  run of 200 cases/pairs on the exact candidate before each official run; size dev runs at 10%.

## Rulings (2026-10-08)
Author: Q1 = policies as DATA allowed for both variants; per-domain/per-model decision CODE = domain_branch for both;
primary audit = consistent renaming test. Q2/Q3/Q6/Q13 = accepted as written (three fixtures hierarchical/collegial/
polycentric with the P1e-1 distinctness rule; H25 floors PROT-H25 s7; H26 floors PROT-H26 s9; no case_view API).
Q4 = no shared visibility helper (only forms and tool_schema shared). Q7/Q8 = D1-D4 accepted; activity volume (D2) and
D4 outcomes recorded as scope limits; chain fields auditor-only (no principal-verifiable redacted chain in Round 3).
Orchestrator: Q5 yes (any preregistered falsifier -> REJECTED); Q9 yes (frozen check order token -> schema -> authority ->
existence; H23/H24/H27 suites + one H23 dev run as regression; official verdicts untouched); Q10 yes; Q11 yes (extra
mutants domain_privilege_branch, subscription_unfiltered, redaction_fabrication); Q12 yes (read() in scope, redefined in
P1e); Q14 yes (no grandfathering on set_governance); Q15 yes (parallel official runs; smoke run of 200 on the exact
candidate first; dev runs at 10%).

## Errata (2026-10-08, after P1e, before any Gate 3 builder)
G3-E1 v3 authority fixtures `spec/authority/<domain>.v3.json` (P1e-6): created by a bounded shared step (P1e-b) before
      any builder: v2 base + a disclosure document such that every fact kind of PROT-H26 s1.1 is protected from at least
      one principal, at least one public type and one protected type exist, `via` rules are used, and every provenance
      level (none/own/scalars/actors) occurs. Added to FREEZE_G3 when created.
G3-E2 Meter attribution of `seed`-tagged world transactions (P1e-8) is implemented in r3_oracle by the Gate 3 harness
      builder (seed transactions are setup, never a candidate effect).
G3-E3 Public schema-level visibility: P1e-6 `public_types` / `public_links` lists are binding; PROT-H26 s1.2 "types with
      public: true" means "types listed in public_types".
G3-E4 tool_schema of a `json`-typed input is the empty schema `{}` (any value).
G3-E5 Governance static rules: unknown body references (competent / review.by / grantees_from) -> invalid; duplicate
      members allowed (set semantics); emergency matter with empty operations -> invalid; the governance document's
      `domain` must equal the authority spec's domain -> otherwise invalid.
G3-E6 Event form: link/unlink events carry `link` and `props: {}`; object events carry `ref` and `props` (low values only).
G3-E7 Decision-view form check = the 12 exact keys; each value is either the true value or a valid marker. WHICH fields
      are true vs redacted is decided only by the oracle (PROT-H26 s4.2); over-redaction is measured by the s9 floor.
G3-E8 Constitutional action schemas: every listed key is required; `on_behalf_of` is required and may be null.
G3-E9 Hierarchy kinds: chain = every body has <= 1 superior and <= 1 subordinate; tree = <= 1 superior; dag = some body
      has >= 2 superiors; none = no superior relations.
G3-E10 Static-rule parity (P1e-9) is checked against the real r3_oracle by the H25 harness builder as a conformance test.
G3-E11 read() redefinition (ruling Q12): bodies follow the P1e-5 forms; existing H23 tests (reading body["props"]) remain valid.
G3-E12 (author decision 2026-10-08, before any G3 measurement) Declared low D5: capability-edge ids (PROT-H24 s1) are
      caller-chosen in ONE public namespace. A delegate whose edge id collides with ANY existing edge (visible or hidden)
      answers INVALID `duplicate_edge`; the set of occupied edge ids is low for every principal. Nothing else about a
      hidden edge (issuer, child, parent, scope, expiry, revocation) is low. Recorded as a scope limit in the H26 SUMMARY.
G3-E13 PROT-H26 via-rule coverage: s1.2 is binding - a via rule covers T:k when a link lt connects T:k to an
      existence-visible T2 object, whether or not that link itself is visible; s2.1 "through visible links" is read as
      "through links to already-visible objects". (Under the literal s2.1 reading two frozen project rules could never fire.)
G3-E14 H25 points PROT-H25 leaves open - the oracle's choices (r3_oracle at r3-g3-h25-harness, listed in BUILD_NOTES
      "G3 H25 harness") are binding: (1) `end` by a non-member of the declaring body -> DENIED (any reason); (2) a lapse is
      fixed at propose_tick + after (pure logical time; the recording transaction may come later); (3) specialis across
      multi-matter bodies as implemented by the oracle; (4) deciding matter = the first covering matter naming the
      winner; (5) a case no longer governed after set_governance -> AWAITING; (6) execute of a declare case is undefined
      and never generated; (7) an ordinary governed request: valid + authorised -> case_required, otherwise any refusal;
      (8) commit point = the governance mark's seq; (9) a refusal that some real-time order would have let commit =
      progress_loss (blocks SUPPORTED), not a mismatch. Variants align; reasons stay informational where the oracle
      accepts "any reason".
G3-E15 Both variants declare every new HistoryStore record prefix they add in Gate 3 (governance cases, decision index,
      governance documents) in HISTORY_LAYOUT, so the H27 tamper discovery keeps full coverage.
G3-E16 Scope note: the H25 renaming audit renames principal, body and model ids; relation names are ops-spec vocabulary
      and are not renamed (recorded in the H25 SUMMARY).
G3-E17 (2026-10-08, after G3 conformance attribution g3-attr1, before any G3 measurement) Post-authority order for every
      mutating call and for constitutional execute/act: deny business rules -> target existence (E-6) -> preconditions ->
      approvals, exactly r3_oracle ops_model.evaluate. A request failing both a deny rule and a precondition answers DENIED.
      (PROT-H25 s3.4 and PROT-H26 s3.2 group these steps without fixing their internal order.)
G3-E18 Case visibility (PROT-H25 s3.1): a case is visible to its requester and to the members of every body listed in
      `competent` of EVERY matter covering the case's operation/resources, and of each such matter's review.by - before
      precedence is applied.
G3-E19 list_links and prov_object on an absent OR hidden ref answer OK with empty lists ({"partial": true, "decisions": []}
      for prov_object), identically (hidden == absent). read_object keeps not_found.
G3-E20 query arguments: resource-typed args take the bare key exactly like operation inputs; other args are typed per the
      ops spec `reads` definition; a wrongly typed or unknown arg -> INVALID (schema).
G3-E21 Provenance digest/field lowness is decided only by the oracle (restates G3-E7 / PROT-H26 s4.2): a variant that
      redacts a value the oracle classifies as low commits over-redaction (s9 floor); own decisions are not exempt from the
      oracle's computation.
G3-E22 (orch, 2026-10-08, clarification of s4.2 + G3-E21, before any H26 measurement) The own-decision exemption covers
      args_digest only (the observer supplied those bytes). effect_digest covers the decision transaction's full world_log
      rows (E-4 form, G3 H26-H), whose data.props/patch include every property of each touched object; it is true only if
      every such object and field is in the observer's low view, else {"redacted": "effect_digest"} - own decisions
      included. Found when the oracle-backed honest fake was REJECTED (divergence on pair p1-27: hidden `path` in the rows
      of its own write); both variants answered the true digest and must redact (equal fix for both).
G3-E23 (orch, 2026-10-08, before any H26 measurement) list_links with a link_type that is not in the ops spec answers
      exactly as the oracle low view (r3_oracle/disclosure_reads.expected_list_links): OK {"out": [], "in": []}, never
      INVALID. Link types are public, so either answer is noninterferent; one form is fixed for fairness (the oracle's).
      Found in review: paladin answers OK (fix2), conventional INVALID unknown_link_type.
G3-E24 (orch, 2026-10-08, after dev1, before any official H25 run) A5(c) auditor review, made explicit and symmetric:
      (1) The scan's hit list is reviewed by the equivalence auditor BEFORE the official run and the review is frozen as
      spec/gate3/DOMAIN-AUDIT-RESOLUTIONS.json: entries keyed by (variant, file, normalised source text of the hit line),
      each with a reason. A hit is resolvable only if it (i) dispatches on a DOMAIN NAME (never a model, body, principal,
      role or relation id) to select which IR / ops-spec helper / adapter set to load, and (ii) neither the selector nor the
      selected branch reads principals, roles, grants, tokens, approvals, governance, bodies or disclosure; or (iii) the
      literal is a role/relation name that coincides with an unrelated vocabulary word and the code does not touch
      authority (listed with that reason). Every unresolved hit counts as domain_branch; the resolution file cannot be
      changed after the official run starts. (2) Code guarded by a mutant switch ("<name>" in self.mutants /
      self.mutant("<name>")) is scanned only in the build where that mutant is active (the A5(d) self-test still runs on
      the domain_privilege_branch build). (3) DOMAIN_LOGIC_MODULES is read from each variant's declaration where it is
      declared (variant.py or package __init__), matched by path. (4) The renaming test (A5a) is unchanged and remains
      the primary criterion; no resolution can excuse a renaming difference.
      Clarifies PROT-H23 R5 for constitutional `act` (no change, oracle already does this): a replay re-evaluates the
      authority in force now INCLUDING the emergency grant (active, unexpired, in scope), not base grants only.
G3-E25 (orch, 2026-10-08, after dev1, before any official H26 run) Marker kinds (P1e-5 list actor|digest|edge|args):
      args_digest redacts to {"redacted":"args"}; effect_digest, artifact digests and authority_version redact to
      {"redacted":"digest"} (G3-E22's `{"redacted":"effect_digest"}` was a typo for "digest"). The oracle
      (disclosure_prov) emits "args" for args_digest. Found in dev1: both variants already emitted "args".
G3-E26 (orch, same) Public types (PROT-H26 1.2 public:true) grant existence, all fields and all links only. A decision is
      low iff it is own, or every resource input is existence-visible AND covered by a disclosure rule whose provenance
      is scalars|actors (s4.1, literal); public:true is not such a rule, so its provenance level is `none`.
      Restates INTERP-2 for args_digest of a non-own decision: true only if the args are made only of existence-visible
      resource refs (no scalar inputs present); "the scalar flows into a visible field" does not make args low.
G3-E27 (orch, same) In principal provenance views, `reason` of a decision equals the `reason` of the public reply body of
      the same request ("ok" for OK); internal gate codes are auditor-only (PROT-H27 auditor envelopes unchanged).
      authority_used_as(token, rid) on an OWN request answers whenever prov_decision answers that rid: for a refused
      request path = [] (no authority was used); both views must agree on whether the rid exists.
G3-E28 (orch, same) H26 generated worlds (both members of a pair, after the high phase) satisfy every ops-spec invariant;
      a draw whose predicted snapshot violates one is re-drawn. D4 probes target only operations the observer may call
      directly (not governed, PROT-H25 s3.4) or carry the oracle's constitutional expectation. The exfiltration canary
      scan ignores canary values present in the observer's own request.
G3-E29 (author decision 2026-10-08 + orch amendment of G3-E24(iii), after the first hit review, before any official H25 run)
      (a) AUTHOR: A5(c) hits in a variant's domain logic modules that hard-code ops-spec business rules about authority
      (approval thresholds, relation/role checks such as planner/supervisor) COUNT as domain_branch (Q1: per-domain
      decision code). A variant may, before the official run, replace such code by evaluation of the shared ops-spec
      data; resolutions under G3-E24(1)(i) for the domain-name selector of such modules (e.g. a bindings loader) apply
      only once the selected modules no longer read authority. Applies equally to both variants.
      (b) ORCH, G3-E24(iii) restated symmetric and mechanical: a hit whose literal is a value or key of a FROZEN PROTOCOL
      field - P1e provenance levels none|own|scalars|actors, P1 delegation record keys agent|on_behalf_of|operations - and
      that is compared with / indexes that protocol field (never a principal's role or relation) is resolvable, even in
      disclosure or delegation code. It coincides with a fixture role name only by accident (roles `none`, `agent`).
G3-E30 (orch, 2026-10-08, after dev2, before any official H26 run) Extends G3-E28: a hidden variation may only produce
      state reachable through ops-spec operations. In particular vary_L only adds/removes link types that some ops-spec
      operation creates or removes (project: TESTED_BY is created by none, so it is seed-only and never varied); invariants
      the harness cannot evaluate on one snapshot do not excuse an unreachable variation. Found in dev2: pair p2601-97 added
      TESTED_BY H-D -> E-F@v1, which made the stored verdict of H-D disagree with derive_verdict (verdict-machine-derived);
      Paladin's state-level gate then refused every write in that world only. Attribution: reports/g3-attr3-p97-report.md.
G3-E31 (orch, 2026-10-09, after official exp-h25-001 / exp-h26-001, before exp-*-002) (a) Ops-spec business rules: the formal
      `when` expression binds; the prose `text` is commentary (preregister/contract-complete: a blank freeze_hash is a
      precondition failure -> INVALID, as the oracle answers, not a deny rule). (b) H26 official runs go through
      scripts/run_h26.sh (HistoryStore + AnchorClient per ruling Q10); scripts/run_h26.py refuses a non-dev id without an
      anchor. The smoke run uses the identical launcher. exp-h26-001 ran without an anchor (orchestrator launch fault).
G3-E32 (orch, 2026-10-09, after official exp-*-002, before exp-*-003) (a) A decision that completes by re-evaluation under a new
      governance document (Q14, no grandfathering) takes the tick of the judgment that completes it, not the tick of
      set_governance; the appeal window runs from that tick (oracle const_eval, conventional agree). (b) H26 pairs: both
      worlds append the same number of world_log rows in every phase (equal schedules, declared low fact D2); a draw whose
      composed batches differ in row count (e.g. a hidden write that is a no-op in one world) is re-drawn.
G3-E33 (AUTHOR, 2026-10-09, pre-registered before exp-*-003 runs) exp-h25-003 and exp-h26-003 are the FINAL official Gate 3
      attempt: their verdicts are the Gate 3 result for both variants. Only a run made invalid by a harness or launch fault
      (not a variant defect) may be repeated, and only by a new author decision. The Gate 3 summary reports, per variant and
      hypothesis, the number of official attempts and the attributed cause of every rejection (exp-*-001, -002 ATTRIBUTION.md).
