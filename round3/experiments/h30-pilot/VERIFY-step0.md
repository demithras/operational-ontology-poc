# H30 pilot - step 0 orchestrator verification (2026-10-16)

Analysis: `step0-report.md` (read-only static analysis of round3 HEAD d02cbcd, Opus agent, blind to experiments/ and RESULTS.md).
Counts: 9 CANDIDATE, 14 BR-NEUTRAL, 1 SHARED, 0 UNKNOWN (24 cells).

## Known-positive control: PASSED
The report's D3 ("conventional skips expired intents; Paladin keeps submitting and the server refuses `expired`; extra refused
audit rows, no applied rows; BR-neutral") is the Gate 5 finding (exp-h29-001r3 SUMMARY:65,78-80), found unprompted and classified
correctly as a different mechanism without a BR difference.

## Candidate mechanisms, checked against the cited code
| Id | Cells | Predicted | Code check | Nature of the difference |
|---|---|---|---|---|
| M1 approval exclusion timing | A1/A2 obj, ext | BR_P > BR_C | CONFIRMED. Paladin checks edge issuers only when the approval is recorded (paladin/deployment.py:337); at consume, claim_approval's verify (paladin/core.py:454-468) checks only that the approval is anchored and unconsumed, and engine/pipeline.py decide_approval checks only static chains. Conventional re-computes approval_forbidden at consume (conventional/service.py:510-516). | The two builds read PROT-H24:67-68 "at the approval's commit point" differently (Paladin's reading is arguably the literal one). Spec ambiguity, not architecture. |
| M2 subscribe/poll lease gate | A3/A5 disc; A1/A2 disc weak | BR_C > BR_P | CONFIRMED. Conventional subscribe/poll (conventional/lowevents.py) call no _g5_pregate/AUTH probe and build views from the cached self._policy; read/list/query do gate (lowreads.py:28-35). Paladin routes subscribe/poll through _low, which probes AUTH, in H29 mode only (paladin/deployment.py:252-283). | A missing gate on two conventional surfaces; a few lines to fix. An omitted obvious baseline control (FAIRNESS.md), not architecture. |
| M3 anchor completion from HistoryStore | A6 prov | BR_P > BR_C | MECHANISM CONFIRMED, OUTCOME NOT. paladin/continuity.py:141-182 rebuilds the missing anchor entry from led/pend/<rid> (written by core_g2.py:310-315 into the HistoryStore) taking sub/obo/op/args/path/evidence/doc as stored; only rows come from the world log. Whether replay (replay.py, authreplay.py) then answers VERIFIED for a forged record is not established. | Placement of a journal in attacker-reachable storage; fixable by cross-checking or relocating. Implementation choice, not ontology-specific. |

## Orchestrator reading *(model)*
All three confirmed differences are implementation-level (rule reading, a missing gate, a journal placement), each fixable in a
few lines in the affected variant, and they point in opposite directions (M1, M3 against Paladin; M2 against conventional).
None follows from the ontology-vs-conventional architecture itself. Under H30's own fairness re-measure (PROT-H30 s8.9) M2 would be
patched as an omitted baseline control and M1 settled by an erratum, so real-incident runs would mostly measure these build defects.
The pre-registered stop rule sends confirmed cells to step 1; whether to do that is put to the author (deviation question), not
decided here.
