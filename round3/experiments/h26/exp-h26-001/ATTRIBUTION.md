# exp-h26-001 - attribution (recorded verdicts stand; author decision 2026-10-09)

Official run on tag r3-g3-candidate1 (round3 0841307), seed 2610, runner default sizes, no overrides. Verify: evidence hashes ok,
verdict reproduces. Verdicts: **paladin REJECTED**, **conventional REJECTED** (identical provenance over-redaction 14080 and
false_provenance 3192 in both; paladin also 2 variant errors). Read-only attribution on the immutable evidence: orchestrator
scratchpad reports/g3-attr4-h26-report.md; launch-path cause re-checked by the orchestrator in scripts/run_h26.py.

| Cause | Attribution | Effect |
|---|---|---|
| ORCHESTRATOR LAUNCH FAULT: the official script called `scripts/run_h26.py` directly instead of `scripts/run_h26.sh`; run_h26.py starts the history anchor only for ids containing `-dev` (ruling Q10 needs HistoryStore + AnchorClient), so every world ran without history and both variants answered every provenance call with a whole refusal. The smoke run used a `-dev` id and therefore could not catch it. | (b) harness / launch | 14080 over-redaction + 3192 false_provenance in BOTH (exact) |
| generator: pair p2610-4784 (valdiff decision pair varying PO-991 vs PO-992, both visible to the observer) is not low-equivalent; `gen_vary.vary_D` pins only resource inputs with a scalars-level pool and `gen_pair` skips the visibility check for valdiff - both variants match the oracle per world | (b) harness | 1 divergence in BOTH (seen only in an anchored re-run) |
| paladin `domains/project/logic/derive.py:43` reads `x["git_commit"]`, KeyError when the field is hidden from the observer (PROT-H26 3.3: hidden field behaves like null) | (a) paladin | 2 variant errors (pair p2610-4499) |

Anchored re-run of all 5000 pairs per variant (scratch directory, not evidence): over-redaction and false_provenance drop to 0,
all other tags identical, mutation kill rate 1.0. Not re-run: A/A controls and fuzz with the anchor, a replacement for pair 4784.
A valid measurement needs a new official run (exp-h26-002) through run_h26.sh.
