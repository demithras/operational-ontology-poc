# exp-h26-003 - H26 sovereignty / noninterference (official, FINAL Gate 3 attempt per G3-E33)

Candidate `r3-g3-candidate3` (round3 f4b101d), fresh isolated worktree (HEAD == tag asserted), launched through
`scripts/run_h26.sh` (sandboxed HistoryStore + anchor per variant, G3-E31), seed 2630, runner default sizes. `verdict.json` is
authoritative; `minimum_overrides` is empty; `verify_h26.sh`: evidence hashes ok, verdict reproduces. Pre-registered (G3-E33):
this attempt is the Gate 3 result.

| | paladin | conventional |
|---|---|---|
| Verdict | **SUPPORTED** | **SUPPORTED** |
| Valid low-equivalent pairs / A/A controls (divergent) | 5,000 / 500 (0) | 5,000 / 500 (0) |
| Divergence / existence leak / value exfiltration / provenance overdisclosure | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| False provenance / hidden capability or schema | 0 / 0 | 0 / 0 |
| Read correctness (anti-masquerade floor 1.0) / safe progress | 1.0 / 1.0 | 1.0 / 1.0 |
| Mutants killed (error_detail_leak, existence_status_split, hidden_tool_schema, provenance_edge_retained, redaction_fabrication, subscription_unfiltered) | 6/6 | 6/6 |
| p95 latency (shared host; non-authoritative) | 6.4 ms | 4.4 ms |

Scope limits (declared before results, PROT-H26 D1-D5 and rulings Q7/Q8): activity volume (seq/tick counters) and the outcome
class of authorised writes are declassified; no principal-verifiable redacted chain (chain fields are auditor-only).

## Attempt history (all official attempts stay on record)

| Attempt | paladin | conventional | Attributed causes |
|---|---|---|---|
| exp-h26-001 (seed 2610) | REJECTED | REJECTED | ORCHESTRATOR LAUNCH FAULT: run without the history anchor (14080 over-redaction / 3192 false provenance in both); one non-low-equivalent generated pair (both); paladin KeyError on a hidden field (2 variant errors) |
| exp-h26-002 (seed 2620) | REJECTED | REJECTED | one generated pair with unequal world_log schedules (divergence 7 in both; harness, G3-E32b) |
| exp-h26-003 (seed 2630) | **SUPPORTED** | **SUPPORTED** | - |

Both H26 rejections of conventional and all but one H26 rejection cause of paladin were harness or launch faults (no
measurement of the variants); the remaining paladin cause was its own defect.

Dual-track reading: both variants meet H26 with parity on every leak class; no Paladin-specific value is attributable.
