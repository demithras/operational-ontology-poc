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
