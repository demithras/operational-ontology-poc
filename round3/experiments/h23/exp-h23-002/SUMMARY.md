# exp-h23-002 - H23 compromised-agent effect containment (official)

Candidate `r3-h23-candidate-2` (37b636c), isolated worktree, seed 4271, 10,000 unique sequences per variant (both public
domains), 300 concurrency scenarios, crash/restart/replay scenarios incl. approvals across crashes, mutation proof.
`verdict.json` is the authoritative record; `minimum_overrides` is empty. Sequence logs are gzip-compressed;
`RAW_SHA256.txt` holds the hashes of the uncompressed files.

| | paladin | conventional |
|---|---|---|
| Verdict | **SUPPORTED** | **SUPPORTED** |
| Forbidden committed effects | 0 | 0 |
| Identity / on-behalf-of expansions | 0 | 0 |
| Direct backstop (rejects every tool-surface denial) | 1.0 | 1.0 |
| Crash duplicates / state mismatches / approval lost or reused | 0 / 0 / 0 | 0 / 0 / 0 |
| Concurrency: unserializable / progress lost | 0 / 0 | 0 / 0 |
| Legitimate safe progress | 1.0 | 1.0 |
| Mutants killed (6 frozen) | 6/6 | 6/6 |
| Calls differing between the variants | 0 of 96,481 | |
| p95 latency, legitimate calls (CONTENDED host, non-authoritative) | 17.4 ms | 1.3 ms |
| Python LOC of the variant (excluding unchanged vendored Round 2 code) | 1,672 (5,099 total) | 1,370 |

Context:
- This supersedes nothing: exp-h23-001 (candidate 01bc7ac) stays on record as REJECTED for both variants
  (`../exp-h23-001/ATTRIBUTION.md`). Between the two runs both variants were tightened identically to the protocol text
  (an approval binds `on_behalf_of` literally; author decision 2026-10-07) and the world store moved to WAL so the effect
  meter survives lock contention. The exp-h23-001 failure pattern was exercised 3 times per variant in this run and
  produced no flag.
- Dual-track reading (protocol/DUAL_TRACK.json): both variants meet H23. At this gate the comparison is parity on every
  security outcome; Paladin costs more latency and more code. No Paladin value is attributable at this gate.
- Host load was high during the run (a VM and other sessions outside this experiment), so latency figures are
  contended and are not used by any H23 clause.
