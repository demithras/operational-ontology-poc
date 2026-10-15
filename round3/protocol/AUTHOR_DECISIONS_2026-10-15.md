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
