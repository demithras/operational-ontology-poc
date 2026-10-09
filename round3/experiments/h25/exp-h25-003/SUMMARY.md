# exp-h25-003 - H25 constitutional governance (official, FINAL Gate 3 attempt per G3-E33)

Candidate `r3-g3-candidate3` (round3 f4b101d), fresh isolated worktree (HEAD == tag asserted), seed 2530, runner default sizes,
both variants on the identical seeded corpus (parallel processes). `verdict.json` is the authoritative record;
`minimum_overrides` is empty; `verify_h25.sh`: evidence hashes ok, verdict reproduces. Files over 2 MB are gzip-compressed;
`RAW_SHA256.txt` holds the hashes. Pre-registered (G3-E33, author, before the run): this attempt is the Gate 3 result.

| | paladin | conventional |
|---|---|---|
| Verdict | **SUPPORTED** | **SUPPORTED** |
| Unique cases (incl. races, no-governance) | 10,338 | 10,338 |
| Governance models (structurally distinct) | 3 | 3 |
| Domain-specific privilege branches (renaming audit + reviewed static scan, spec/gate3/DOMAIN-AUDIT-RESOLUTIONS.json) | 0 | 0 |
| Procedural equality with the oracle | 1.0 | 1.0 |
| Fabricated judgments / emergency violations / forbidden effects | 0 / 0 / 0 | 0 / 0 / 0 |
| Legitimate progress (floor 1.0) | 1.0 | 1.0 |
| Mutation kill rate | 1.0 | 1.0 |
| p95 latency (host shared with 3 other runs; non-authoritative) | 28.3 ms | 2.4 ms |
| Security-specific LOC (excluding unchanged vendored code) | 4,999 (7,588 total) | 3,443 |

## Attempt history (all official attempts stay on record)

| Attempt | paladin | conventional | Attributed causes (ATTRIBUTION.md in each experiment) |
|---|---|---|---|
| exp-h25-001 (seed 2510) | REJECTED | INCONCLUSIVE | paladin: 15 procedural mismatches (own code: absent-target deny rules, blank freeze_hash); both: harness generator never produced refusal class `already_judged` (coverage) |
| exp-h25-002 (seed 2520) | REJECTED | **SUPPORTED** | paladin: 3 procedural mismatches (own code: non-total helper on an absent experiment; decision tick on re-evaluation, G3-E32) |
| exp-h25-003 (seed 2530) | **SUPPORTED** | **SUPPORTED** | - |

Conventional met H25 on its 2nd official attempt and again on the 3rd; Paladin needed 3 attempts, each after fixing its own
defects. Paladin also reworked its vendored Round 2 manufacturing rules into evaluation of the shared ops-spec data before any
official run (author decision G3-E29: hard-coded domain business rules count as domain branches).

Dual-track reading (protocol/DUAL_TRACK.json): both variants meet H25 with parity on every security outcome; Paladin is slower
and larger and needed more attempts. No Paladin-specific value is attributable at this hypothesis.
