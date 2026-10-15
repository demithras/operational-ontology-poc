# exp-h25-001 - attribution (recorded verdicts stand; author decision 2026-10-09)

Official run on tag r3-g3-candidate1 (round3 0841307), seed 2510, runner default sizes, no overrides. Verify: evidence hashes ok,
verdict reproduces. Verdicts: **paladin REJECTED** (procedural_mismatch 15 + coverage gap), **conventional INCONCLUSIVE**
(coverage gap only). Read-only attribution on the immutable evidence: orchestrator scratchpad reports/g3-attr4-h25-report.md;
two claims re-checked in code by the orchestrator.

| Cause | Attribution | Effect |
|---|---|---|
| `edit_threshold` on an absent threshold: paladin `domains/project/logic/policies.py::_threshold_edit_denied` uses `any()` over an empty target set, so the deny rule never fires -> INVALID not_found where the oracle (G3-E17: deny rules before existence) answers DENIED | (a) paladin | 11 procedural_mismatch |
| `evaluate_hypothesis` / `record_decision` on an absent target: paladin policies raise on the absent target and the pipeline defers to the existence check | (a) paladin | 1 + 1 |
| `preregister_hypothesis` with a blank `freeze_hash`: paladin folds it into the deny policy (DENIED) where the oracle answers INVALID precondition; the rule's prose mentions freeze_hash, its formal `when` does not | (a) paladin + (c) text gap | 2 |
| refusal class `already_judged` never generated for the hierarchical model: dead abstain branch in `r3_harness/h25/plays_a.py::run_stage` (`partial` with need == 1 gives limit 0) - same at the dev seed; dev passed only because its coverage floors were relaxed | (b) harness | coverage floor unmet for BOTH variants |

Counterfactual (probe-only patches, not a verdict): the three paladin fixes clear all 15 mismatches, leaving paladin INCONCLUSIVE
like conventional; the generator fix produces 742 hierarchical `already_judged` rows. A SUPPORTED verdict for either variant needs
a new official run (exp-h25-002).
