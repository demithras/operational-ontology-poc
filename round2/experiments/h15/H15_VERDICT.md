# H15 verdict — OpenPona as a lossless Ontology Language surface

**Verdict: SUPPORTED** under the frozen protocol (freeze 1b70e389…, Gate-0 2b632c47…, candidate ea573d8c…).
Authoritative evidence: `exp-h15-002/` (clean commit 0839223, seed 15). `exp-h15-001/` agrees but had only
9,789 unique packages among its 10,000 cases, so exp-h15-002 was run with 10,400 cases (10,175 unique).
Thresholds were not changed; a larger sample could only add failures.

| Measure | exp-h15-002 |
|---|---|
| Generated valid cases / unique | 10,400 / 10,175 |
| OpenPona round trips exact | 10,400 / 10,400 (DSL baseline 10,400 / 10,400) |
| Real domains equivalent | manufacturing, project |
| Declared ambiguity cases fail closed | 44 / 44 |
| Deletion mutants with invented semantics | 0 / 3,280 |
| Indispensable sidecar fields / new tokens / gaps | 0 / 0 / 0 |
| Target compiler mutants killed | 6/6 OpenPona, 6/6 DSL |

## Read the verdict with these caveats

1. **The whole reference graph rests on coreference labels.** 181/181 (manufacturing) and 204/204 (project)
   reference slots are carried by enumerated `<head> pi X Y` labels with no gloss content. Orchestrator ruling
   (`protocol/H15_PHASE2_DECISIONS.md` #1) allows them because they encode identity only (bijective renaming
   leaves the IR unchanged). Under the stricter reading "arbitrary token labels are a cipher", H15 is REJECTED
   on this same evidence.
2. **What SUPPORTED proves.** OpenPona can carry the frozen IR losslessly via a 92-rule template encoding with
   canon-gloss justifications. It does not show the encoding is natural: numeric types (`integer` = `kulupu ijo`,
   `number` = `kulupu pilin`), `date` = `tenpo sike` and `git_change` = `sitelen` are weak glosses, because none
   of the 42 tokens means a number.
3. **Cost versus the direct DSL** (manufacturing): 1.66x bytes, 1.30x lines, 2.80x tokens; compiler + renderer
   1,164 LOC versus 402 LOC (parser not counted). OpenPona brings no measured compactness benefit.
4. **Process disclosures.** Two exp-h15-001 runs were discarded before the recorded one (run0 INCONCLUSIVE:
   too few deletion mutants; run1 SUPPORTED before a generator-isolation fix); all had 0 failures. Only the
   orchestrator's rulings and the anti-cipher rule R4 were added after the freeze, all before the Phase 3 run.
