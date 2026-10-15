# Author decisions 2026-10-15 (Gate 6 / H30 task source)

## 1. H30 blind tasks come from public incident patterns (supersedes AUTHOR_DECISIONS_2026-10-06 s3)
Decision (author, AskUserQuestion 2026-10-15, after Gate 5 closed with exp-h29-001r3): the >= 40 blind realistic tasks across >= 5
attack classes are built from PUBLIC patterns (published incident reports, CVE / advisory write-ups, OWASP LLM / agentic top-10
cases, confused-deputy and supply-chain case studies), not from employer material. Consequences:
- Everything is public on branch `round3`; the private branch `round3-h30-private` is not used.
- To stay inside the H30 contract scope ("mined or adapted from real operational/security change patterns") and away from its rival
  and falsifier about synthetic-only cases, every task must cite the real public source it is adapted from (URL or identifier) and
  state which elements are adapted; a task without a citable real source is not admissible to the realistic tier.
- The task corpus is authored by a separate task-author agent and sealed (hash in the freeze) before either variant or the harness
  sees it; variants are frozen before reveal (contract experiment step 1).
Thresholds in protocol/thresholds.json are unchanged.

## 2. Gate 6 design rulings (author, AskUserQuestion 2026-10-15)
- Q-A3: H30 is REJECTED whenever no attack class is MATERIAL or UNCERTAIN, regardless of recurring cost (contract falsifier 1 governs).
- Q-A4: a class is MATERIAL iff the upper end of the distribution-free order-statistic interval of the median ratio is within the
  threshold (n = 10: [x(3), x(8)]); EXCLUDED iff its lower end exceeds it; otherwise UNCERTAIN.
- Q-A5: recurring security-specific machinery = SLOC + config surface over an auditor-classified scope frozen before sealing.
- Q-A1, Q-A2, Q-A6..Q-A14 accepted as recommended in spec/gate6/OPEN-QUESTIONS.md (6 classes x 10 tasks A1/A2/A3/A5/A6/A7, >= 8 of 10
  complete; one comparative verdict + per-variant safety record; incorrect recovery = safety regression; primary + reserve sealed corpus,
  at most 2 corpus attempts; fixed operator containment ladder L1-L6; A4 excluded; fairness audit controls <= 300 SLOC, <= 2 rounds;
  COST = containment + recovery actions; safe progress <= 5 pp pooled and per class; latency P C C P P C, worst pair <= 2.0, A/A band
  [0.8, 1.25]; this decision supersedes DUAL_TRACK.json publication.private for H30 without editing that frozen file).

## 3. Domain mix of the H30 corpus (author, AskUserQuestion 2026-10-15)
Both domains by class (G6-E3): A1/A3/A5/A6 half "project", half "manufacturing"; A2/A7 "manufacturing" only (declared scope limit:
the frozen project overlay has no delegations or external targets). Chosen over extending the project overlay and over a single domain.

## 4. H30 is not run; Round 3 closes on H23-H29 (author, AskUserQuestion 2026-10-15)
Decision: stop Gate 6 and close Round 3. Reason given to the author and accepted: H23-H29 are SUPPORTED for BOTH variants with
parity on every frozen metric and no measured Paladin-specific advantage in any gate (Gate 4 and Gate 5 SUMMARYs), and one measured
Paladin weakness (Gate 5: resubmission of expired external effects); a synthetic task corpus (author decision 2026-10-15 s1) cannot
convincingly overturn that under the H30 contract's own rival/falsifier about synthetic-only advantage, while costing ~1-2 days.
H30 status: NOT RUN (no verdict; not REJECTED, not SUPPORTED). Gate 6 design, errata G6-E1..E3, P1h shared plane and the dev-corpus
authoring record stay on round3 as documentation; the unfinished builder work stays on local branches (r3-paladin 0ec5166,
r3-conv 95f1b6b, r3-harness 46a5151, r3-legit af66706), not merged and not reviewed.
