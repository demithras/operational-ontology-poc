# Round 2 v2 results — H15–H22w

A view over the committed evidence, not evidence itself. Authoritative files: `experiments/hNN/<exp-id>/verdict.json`.
Protocol freeze `1b70e389…` (`protocol/FREEZE.json`); preregistration `protocol/ENGINE_PREREG.json` (tag `r2-engine-prereg`);
author decisions `protocol/AUTHOR_DECISIONS_2026-10-03.md`. Branch `round2-v2`.

## Final verdicts

| Hypothesis | Final verdict | Authoritative evidence | Tag |
|---|---|---|---|
| H15 OpenPona as lossless Ontology Language | **SUPPORTED** (v2: no labels, ids as record metadata) | `experiments/h15/exp-h15-v2-001` | `r2-h15v2-exp001` |
| H16 bounded kernel across two domains | **SUPPORTED** | `experiments/h16/exp-h16-001` | `r2-h16-exp001` |
| H17 Function ≠ Action hard boundary | **SUPPORTED** on Engine v1.2 | `experiments/h17/exp-h17-004` | `r2-h17-exp004` |
| H18 Project Ontology as executable second domain | **REJECTED** | `experiments/h18/exp-h18-001` | `r2-h18-exp001` |
| H18w (post-hoc) the executable Project Ontology works | **SUPPORTED** (claim formulated after H18's result) | `experiments/h18/exp-h18w-001` | `r2-h18w-exp001` |
| H19 Git authority without split brain | **SUPPORTED** (upstream: H18w) | `experiments/h19/exp-h19-001` | `r2-h19-exp001` |
| H20 one generic Engine, no domain branches | **SUPPORTED** on Engine v1.2, no exceptions | `experiments/h20/exp-h20-002` | `r2-h20-exp002` |
| H21 Toolchain generated with security equivalence | **SUPPORTED** on Engine v1.2 | `experiments/h21/exp-h21-002` | `r2-h21-exp002` |
| H22 semantic-variety break-even | **REJECTED** (3 domains, 33 blind tasks, 66 attempts) | exp-h22-002, private branch (not published) | — |
| H22w (post-hoc) schema+generator EOO at parity with the baseline | **REJECTED** (36 new blind tasks, 90 attempts) | exp-h22w-002, private branch (not published) | — |

## Full experiment record (nothing deleted)

| Hypothesis | Run | Candidate | Verdict | Why it is not the final one |
|---|---|---|---|---|
| H15 | exp-h15-001 | OpenPona v1 | SUPPORTED as evaluated | only 9,789 unique cases of 10,000 |
| H15 | exp-h15-002 | OpenPona v1 (enumerated `pi X Y` labels) | SUPPORTED as evaluated → **REJECTED by author decision 1** | every reference slot (181/181, 204/204) relied on labels with no meaning |
| H17 | exp-h17-001 | Engine v1 | **REJECTED** | returned live execution records; editing them executed gate-denied actions |
| H17 | exp-h17-002 | Engine v1.1 | **INVALID** | orchestrator ran another builder in the same working tree during the run |
| H17 | exp-h17-003 | Engine v1.1 | SUPPORTED | superseded by the v1.2 re-run |
| H20 | exp-h20-001 | Engine v1.1 | SUPPORTED with one ruled exception | adapter composed Git trailers; replaced by author decision 2 |
| H21 | exp-h21-001 | Engine v1.1 | SUPPORTED | superseded by the v1.2 re-run |
| H19 | DEPENDENCY_STOP.json | — | STOPPED (H18 rejected) | lifted after H18w was SUPPORTED (`experiments/h19/STOP_LIFTED.md`) |
| H22 | exp-h22-001 (`experiments/h22/exp-h22-001`) | — | INCONCLUSIVE | gate unmet (2 of 3 domains, 0 of 30 tasks); superseded by exp-h22-002 once a third domain and a blind corpus existed |
| H22w | exp-h22w-001 | — | **INVALID** | orchestrator gave attempt agents the task statement instead of the frozen attempt prompt; never measured; re-run as exp-h22w-002 |

## What the result says

The executable machinery works. One kernel serves both domains without new primitives (H16). The Engine enforces a
hard Function/Action boundary once its v1 aliasing bug is fixed (H17). It runs both domains through one generic
lifecycle, and adapters only bind to external systems: they write the provenance the Engine composes byte for byte
(H20). Typed, security-equivalent tool surfaces generate from the contract (H21). OpenPona can carry the IR
losslessly with every word combination meaningful, ids kept as record metadata (H15 v2). The project's own research
lifecycle runs on the same Engine in exact agreement with an independent lifecycle oracle (H18w, post-hoc), with Git as
the single source of truth: deterministic rebuilds, no lost updates, explicit conflicts, history stays pinned (H19).

The value claim fails where it was tested. On the project's own lifecycle, the ontology needed about 4–5x the bespoke
surface of an equally strong Git + JSON Schema + scripts baseline in every preregistered task class, plus 2,191 vs 39
LOC of recurring machinery (H18). This repeats v1's H11 finding on a second domain.

Reuse does not repay the tax as domains accumulate (H22). Across three domains and 33 blind change tasks, each solved
once per variant by a fresh agent, the ontology needed more per-task effort than a strong relational/event baseline in
every change class: class medians 1.31x (source churn) to 6.74x (new relation or query), with more regressions (24 vs 15),
equal security failures (3 vs 3) and 2,763 vs 1,196 LOC of recurring machinery. Per domain: 5.11x and 2.64x on the two
public domains; 1.12x on the third, a read-mostly domain onboarded through a schema generator, but 3.74x there once
generated files count as hand-written. A weaker post-hoc claim, that onboarding through a declarative schema plus a
generator reaches parity, also fails on 36 new tasks (H22w): 1.48x [1.11, 1.68] on manufacturing rebuilt from a schema,
1.84x [1.43, 2.45] on a new synthetic billing domain. The generator cuts the ontology's per-task cost to about a quarter
of the hand-built path (0.28x; hand-built control 5.15x) by removing IR edits, but code edits stay above the baseline.

## Costs and caveats (none changes a verdict)

| Item | Detail |
|---|---|
| H15 v2 cost | text + record are 2.6–2.9x the direct DSL in bytes and 4.9–5.7x in tokens (the OpenPona text alone is 0.85–0.92x; the record repeats target ids for every reference); compiler 1,267 vs 402 LOC |
| H15 weak glosses | number = `kulupu pilin`, date = `tenpo sike`, git_change = `sitelen`: no token among the 42 means a number |
| H15 v2 meaning test | cannot fail for v2 by construction; its teeth are the known-negatives (v1 fails it: 3,190 phrases vs bound 188; injected labels fail it) |
| H17 kill-chain | Engine v1 bypass fixed as new candidate versions (v1.1, v1.2) with the H17 harness unchanged (`protocol/H17_REJECTION_DECISION.md`). Strict alternative: stop H18–H22 after exp-h17-001 |
| H18 | also 7 self-supersession steps accepted (a project policy referenced by no action) and 61 legal version-chain steps refused |
| H18w | post-hoc (formulated after H18's result, frozen before its own run); needed project contract v3 to close two declaration gaps found by exp-h18-001 (`domains/project/CHANGES_v3.md`); lower evidential weight |
| H22 / H22w evidence | kept on a private branch: the third H22 domain's structure and the change archetypes come from private sources (a real ontology and a private repository's commit history); all instance data was synthetic. Published here: aggregates only |
| H22 / H22w method | change archetypes mined from real commit history (classification precision 0.61); the same model family wrote the tasks and solved them; H22w is post-hoc and needed two harness fixes before measurement (prompt; regression goldens), neither touching variants, tasks or oracles; per-variant own-test counts are uneven |
| H19 | upstream changed from H18 to H18w by author decision; contract and thresholds unchanged |
| H20 | real Git adapter covered by one real-action probe (7 writes); the bulk of workloads use the in-process Git fake (232 writes) |
| H21 | oracle and toolchain share an author; the live-Engine cross-check is the second oracle |

## Scope limits

- The Engine is a new in-process engine (`src/eoo_engine`, v1.2). The v1 Docker stack (Temporal, OpenFGA, OPA) was not
  re-platformed (`protocol/ENGINE_PREREG.json`).
- Frozen-IR limits: one decision per Policy; compensation must name a governed Action; no Action object binding. As a
  result, manufacturing `expedite_purchase_order` and `reschedule_work_order` can be authorized for nobody.
- Project contract v2 (`domains/project/ir.v2.json`) fixed one declaration defect before any H16–H22 evidence
  (`domains/project/CHANGES_v2.md`); H15 used the frozen v1 IR; H18w and H19 use contract v3 (`CHANGES_v3.md`).
