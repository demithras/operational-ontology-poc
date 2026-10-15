# exp-h25-002 - attribution (recorded verdicts stand)

Official run on tag r3-g3-candidate2 (round3 9334a6e), seed 2520, runner default sizes, no overrides. Verify: evidence hashes ok,
verdict reproduces. Verdicts: **conventional SUPPORTED** (no reasons; all floors met), **paladin REJECTED**
(procedural_mismatch 3). Read-only attribution on the immutable evidence: orchestrator scratchpad reports/g3-attr5-h25-report.md.

| Cause | Attribution | Effect |
|---|---|---|
| `new_experiment_version` on an absent experiment: paladin `domains/project/logic/payloads.py:46` subscripts `["version"]` on the absent object and raises; the r3-g3-fix9-paladin rule "an erroring deny rule fails closed" (V4) turns it into DENIED policy, while the oracle's total helper falls through to existence -> INVALID (conventional matches the oracle). Residue of the exp-h25-001 absent-target family. | (a) paladin | 2 (differential case-2520-466; judgment-flip probe 2520-268) |
| a decision completed by re-evaluation at `set_governance` (tick 3) is stamped by paladin `procedure.py:198` with the governance tick instead of the completing judgment's tick, restarting the appeal window -> DENIED not_final where the oracle (const_eval.py:168) and conventional give DENIED no_authority. New shape; the frozen text does not say which tick such a decision takes. | (a) paladin + (c) text gap | 1 (case-2520-2509) |

Counterfactual (in-memory monkeypatches only): both fixes clear all 3 rows; conventional unchanged. Whether paladin becomes
SUPPORTED needs a new official run.
