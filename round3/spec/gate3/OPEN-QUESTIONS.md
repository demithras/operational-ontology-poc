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
