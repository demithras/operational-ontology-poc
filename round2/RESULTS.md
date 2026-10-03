# Round 2 v2 results — H15–H22

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
| H19 Git authority without split brain | **STOPPED BY DEPENDENCY** (H18 rejected) | `experiments/h19/DEPENDENCY_STOP.json` | `r2-h19-stop` |
| H20 one generic Engine, no domain branches | **SUPPORTED** on Engine v1.2, no exceptions | `experiments/h20/exp-h20-002` | `r2-h20-exp002` |
| H21 Toolchain generated with security equivalence | **SUPPORTED** on Engine v1.2 | `experiments/h21/exp-h21-002` | `r2-h21-exp002` |
| H22 semantic-variety break-even | **INCONCLUSIVE** (gate: 2 of 3 real domains, 0 of 30 blind tasks) | `experiments/h22/exp-h22-001` | `r2-h22-exp001` |

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

## What the result says

The executable machinery works. One kernel serves both domains without new primitives (H16). The Engine enforces a
hard Function/Action boundary once its v1 aliasing bug is fixed (H17). It runs both domains through one generic
lifecycle, and adapters only bind to external systems: they write the provenance the Engine composes byte for byte
(H20). Typed, security-equivalent tool surfaces generate from the contract (H21). OpenPona can carry the IR
losslessly with every word combination meaningful, ids kept as record metadata (H15 v2).

The value claim fails where it was tested. On the project's own lifecycle, the ontology needed about 4–5x the bespoke
surface of an equally strong Git + JSON Schema + scripts baseline in every preregistered task class, plus 2,191 vs 39
LOC of recurring machinery (H18). This repeats v1's H11 finding on a second domain. Whether reuse repays the tax as
domains accumulate cannot be judged with two domains (H22).

## Costs and caveats (none changes a verdict)

| Item | Detail |
|---|---|
| H15 v2 cost | text + record are 2.6–2.9x the direct DSL in bytes and 4.9–5.7x in tokens (the OpenPona text alone is 0.85–0.92x; the record repeats target ids for every reference); compiler 1,267 vs 402 LOC |
| H15 weak glosses | number = `kulupu pilin`, date = `tenpo sike`, git_change = `sitelen`: no token among the 42 means a number |
| H15 v2 meaning test | cannot fail for v2 by construction; its teeth are the known-negatives (v1 fails it: 3,190 phrases vs bound 188; injected labels fail it) |
| H17 kill-chain | Engine v1 bypass fixed as new candidate versions (v1.1, v1.2) with the H17 harness unchanged (`protocol/H17_REJECTION_DECISION.md`). Strict alternative: stop H18–H22 after exp-h17-001 |
| H18 | also 7 self-supersession steps accepted (a project policy referenced by no action) and 61 legal version-chain steps refused |
| H19 | stopped because H18 failed on its claim; `src/eoo_engine_git` exists if the Git-authority question is to be answered on its own |
| H20 | real Git adapter covered by one real-action probe (7 writes); the bulk of workloads use the in-process Git fake (232 writes) |
| H21 | oracle and toolchain share an author; the live-Engine cross-check is the second oracle |

## Scope limits

- The Engine is a new in-process engine (`src/eoo_engine`, v1.2). The v1 Docker stack (Temporal, OpenFGA, OPA) was not
  re-platformed (`protocol/ENGINE_PREREG.json`).
- Frozen-IR limits: one decision per Policy; compensation must name a governed Action; no Action object binding. As a
  result, manufacturing `expedite_purchase_order` and `reschedule_work_order` can be authorized for nobody.
- Project contract v2 (`domains/project/ir.v2.json`) fixed one declaration defect before any H16–H22 evidence
  (`domains/project/CHANGES_v2.md`); H15 used the frozen v1 IR.
