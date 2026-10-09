# exp-h26-002 - attribution (recorded verdicts stand)

Official run on tag r3-g3-candidate2 (round3 9334a6e) through scripts/run_h26.sh (history + anchor, G3-E31), seed 2620, runner
default sizes, no overrides. Verify: evidence hashes ok, verdict reproduces. Verdicts: **paladin REJECTED**, **conventional
REJECTED**, both with divergence 7 and every other count 0 (no existence leak, value exfiltration, provenance overdisclosure,
over-redaction or false provenance). Read-only attribution: orchestrator scratchpad reports/g3-attr5-h26-report.md.

| Cause | Attribution | Effect |
|---|---|---|
| pair p2620-4955 (kinds G,C,D,L) is not low-equivalent: world 0's L seed batch already links SUPPORTS_OR_REFUTES EV-D1 -> H-F, so the hidden D write `attach_evidence(H-F, EV-D1)` is a no-op there; world 0 appends 99 world_log rows, world 1 100, and every later seq shifts by 1 - visible to the observer through its own world_seq / effect_digest / poll seqs (declared low fact D2: activity volume; pairs must have equal schedules). The generator's low-equivalence check compares only the low-view document, which carries no seq/tick. Both variants match the oracle in each world. | (b) harness (generator) | all 7 divergences in BOTH (3 prov_decision, 3 authority_used_as, 1 poll) |

Counterfactual: dropping the two L seed batches of that pair gives 0 divergences in both variants (not a re-run of the corpus).
