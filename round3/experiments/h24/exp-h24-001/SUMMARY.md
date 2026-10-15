# exp-h24-001 - H24 delegation, revocation and expiry under concurrency (official)

Candidate `r3-g2-candidate` (c7dc324), isolated worktree, seed 2401, both variants on the identical seeded corpus
(run as two parallel processes), frozen G2 specs checked against `protocol/FREEZE_G2.json`. `verdict.json` is the
authoritative record; `minimum_overrides` is empty; `verify_h24.sh`: evidence hashes ok, verdict reproduces. Files over
2 MB are gzip-compressed; `RAW_SHA256.txt` holds the uncompressed hashes.

| | paladin | conventional |
|---|---|---|
| Verdict | **SUPPORTED** | **SUPPORTED** |
| Sequences (unique incl. race cases) | 10,000 (11,575) | 10,000 (11,575) |
| Scope amplifications / stale-or-forbidden effects / cycle grants | 0 / 0 / 0 | 0 / 0 / 0 |
| Linearizability violations; race outcomes equal to the oracle | 0; 1,400 / 1,400 | 0; 1,400 / 1,400 |
| Unaffected legitimate progress (floor 1.0) | 151,900 / 151,900 | 151,965 / 151,965 |
| Overlapping race cases (min 1,000) / overlap fraction (floor 0.50) | 1,314 / 0.94 | 1,306 / 0.93 |
| Max delegation depth exercised | 8 | 8 |
| Mutants killed (non_attenuating_delegation, stale_authority_cache, revoke_commit_reorder, expiry_inclusive) | 4/4 | 4/4 |
| p95 latency, legitimate calls (CONTENDED host, three runs in parallel; non-authoritative) | 49.1 ms | 7.8 ms |

Scope notes:
- Among overlapping revoke-vs-execute (RV) races the effect committed first in every case (paladin 82, conventional 83;
  revoke-first 0). The frozen floor (>= 1 effect-first order) is met; the revoke-wins branch is covered only by the
  sequential SEQ control cases, not under real overlap.
- `explicit_reason_mismatch` (paladin 7,187, conventional 19,509) is informational: reason strings differ from the
  oracle's names (e.g. `no_matching_allow` vs `no_valid_path`); statuses and effects match.
- Errata E-1..E-10 (spec/gate2/OPEN-QUESTIONS.md) were all recorded before this run; dev runs 1-3 and a smoke run preceded
  it (not measurements).

Dual-track reading (protocol/DUAL_TRACK.json): both variants meet H24; parity on every security outcome; Paladin is
slower. No Paladin value is attributable at this gate.
