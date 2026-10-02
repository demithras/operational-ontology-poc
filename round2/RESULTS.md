# Round 2 v2 results — H15–H22

A view over the committed evidence, not evidence itself. Authoritative files: `experiments/hNN/<exp-id>/verdict.json`.
Protocol freeze `1b70e389…` (`protocol/FREEZE.json`), preregistration `protocol/ENGINE_PREREG.json` (tag `r2-engine-prereg`).
Branch `round2-v2`.

## Verdicts

| Hypothesis | Verdict | Authoritative evidence | Tag |
|---|---|---|---|
| H15 OpenPona as lossless Ontology Language | **SUPPORTED** | `experiments/h15/exp-h15-002` | `r2-h15-exp002` |
| H16 bounded kernel across two domains | **SUPPORTED** | `experiments/h16/exp-h16-001` | `r2-h16-exp001` |
| H17 Function ≠ Action hard boundary | **REJECTED** on Engine v1; **SUPPORTED** on Engine v1.1 | `exp-h17-001` (v1), `exp-h17-003` (v1.1) | `r2-h17-exp001`, `r2-h17-exp003` |
| H18 Project Ontology as executable second domain | **REJECTED** | `experiments/h18/exp-h18-001` | `r2-h18-exp001` |
| H19 Git authority without split brain | **STOPPED BY DEPENDENCY** (H18 rejected) | `experiments/h19/DEPENDENCY_STOP.json` | `r2-h19-stop` |
| H20 one generic Engine, no domain branches | **SUPPORTED** | `experiments/h20/exp-h20-001` | `r2-h20-exp001` |
| H21 Toolchain generated with security equivalence | **SUPPORTED** | `experiments/h21/exp-h21-001` | `r2-h21-exp001` |
| H22 semantic-variety break-even | **INCONCLUSIVE** (gate: 2 of 3 real domains, 0 of 30 blind tasks) | `experiments/h22/exp-h22-001` | `r2-h22-exp001` |

## What the result says

The executable machinery works. One kernel serves both domains without new primitives (H16). The Engine enforces a hard
Function/Action boundary once its v1 aliasing bug is fixed (H17). It runs both domains through one generic lifecycle
(H20). Typed, security-equivalent tool surfaces generate from the contract (H21). OpenPona can carry the IR losslessly (H15).

The value claim fails where it was tested. On the project's own lifecycle, the ontology needed about 4–5x the bespoke
surface of an equally strong Git + JSON Schema + scripts baseline in every preregistered task class, plus 2,191 vs 39 LOC
of recurring machinery (H18). This repeats v1's H11 finding (relational baseline at parity, cheaper) on a second
domain. Whether reuse repays the tax as domains accumulate cannot be judged with two domains (H22).

## Caveats and alternative readings (all computable from the committed evidence)

| Item | Ruling used | Alternative reading |
|---|---|---|
| H15: every reference slot (181/181, 204/204) is a coreference label with no gloss content | Allowed (identity only; bijective renaming leaves the IR unchanged), `protocol/H15_PHASE2_DECISIONS.md` | Labels are a cipher → H15 **REJECTED** |
| H15: weak glosses for number/date/git_change; OpenPona 1.66x bytes, 2.8x tokens, 2.9x compiler LOC vs direct DSL | Not part of the lossless criterion | — |
| H17: Engine v1 bypass fixed as a new candidate version, H17 re-run unchanged | `protocol/H17_REJECTION_DECISION.md` | Strict kill-chain: H17 rejected → H18, H20, H21, H22 stop by dependency |
| H17: exp-h17-002 INVALID | Orchestrator ran H18's builder in the same tree during the run | — |
| H18: 7 self-supersession steps accepted (conflict policy referenced by no action); 61 legal version-chain steps refused | Recorded; the verdict is already REJECTED on R2 | — |
| H19: dependency stop | H18 failed on its claim, not a fixable defect | Run H19 as a new version against `src/eoo_engine_git` |
| H20: Git commit trailers written by the Git store adapter | Not governance (docs/05 requires Git-visible traceability), `protocol/H20_RULINGS.md` | Exception rejected → H20 **REJECTED** (strict count 1) |
| H21: oracle and toolchain share an author | Live-Engine cross-check (555k decisions in the dev run) as second oracle | — |

## Scope limits

- The Engine is a new in-process engine (`src/eoo_engine`, v1.1). The v1 Docker stack (Temporal, OpenFGA, OPA) was not
  re-platformed (`protocol/ENGINE_PREREG.json`).
- Frozen-IR limits found on the way: one decision per Policy; compensation must name a governed Action; no Action
  object binding. As a result, manufacturing `expedite_purchase_order` and `reschedule_work_order` can be authorized for nobody.
- The project contract v2 (`domains/project/ir.v2.json`) fixed one declaration defect before any H16–H22 evidence
  (`domains/project/CHANGES_v2.md`); H15 used the frozen v1.
