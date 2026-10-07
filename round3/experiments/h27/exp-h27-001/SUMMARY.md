# exp-h27-001 - H27 decision provenance is tamper-evident (official)

Candidate `r3-g2-candidate` (c7dc324), isolated worktree, seed 2701, each variant run under `scripts/run_sandboxed.sh`
(anchor = separate OS process with its own key; harness+variant process under macOS sandbox-exec denying writes to the
anchor directory). Frozen G2 specs checked against `protocol/FREEZE_G2.json`. `verdict.json` is authoritative;
`minimum_overrides` is empty; `verify_h27.sh`: evidence hashes ok, verdict reproduces. Files over 2 MB are
gzip-compressed; `RAW_SHA256.txt` holds the uncompressed hashes.

| | paladin | conventional |
|---|---|---|
| Verdict | **SUPPORTED** | **SUPPORTED** |
| Tampered cases / distinct base histories / clean controls | 5,000 / 600 / 1,000 | 5,000 / 600 / 1,000 |
| Tamper classes (T1-T8 ~860-910 each, T9 continuation 420, 1,240 compound) | identical corpus | identical corpus |
| Affected decisions detected (TAMPERED or UNRESOLVED) | 19,234 / 19,234 | 19,231 / 19,231 |
| Tampered history accepted / rebinding accepted / fallback to current | 0 / 0 / 0 | 0 / 0 / 0 |
| False alarms on clean controls | 0 | 0 |
| Binding divergences from the oracle's expected bindings | 0 | 0 |
| Deploy crashes / unanchored acknowledgements | 0 / 0 | 0 / 0 |
| Mutants killed (digest_omission, fallback_to_current, evidence_rebinding, receipt_self_trust) | 4/4 | 4/4 |
| Anchor E1-E5 (separate process; key only at close; sandbox; 4 write probes PermissionError; HMAC chain + head) | all true (11,494 entries) | all true (10,784 entries) |
| p95 replay latency (CONTENDED, non-authoritative) | 6.0 ms | 1.2 ms |

Scope notes:
- Bound evidence = resource inputs + `newest` terms; business rules are not replayed (author decision 2026-10-07 #2c).
- Counting: tampered cases (>= 5,000) from >= 600 distinct base histories in both domains (decision #2c).
- Errata E-1..E-10 recorded before this run; dev runs and a smoke run preceded it (not measurements).

Dual-track reading: both variants are tamper-evident under the same anchor class; parity on every security outcome;
Paladin replays slower. No Paladin value is attributable at this gate.
