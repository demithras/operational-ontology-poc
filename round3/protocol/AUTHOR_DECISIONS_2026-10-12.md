# Author decisions - Gate 5 (H29) design freeze (2026-10-12)

Frozen before any Gate 5 implementation: `spec/protections/PROT-H29.md`, `spec/gate5/{PROTOCOL-P1g.md,
ORACLE-AND-HARNESS-G5.md,EQUIVALENCE-G5.md,OPEN-QUESTIONS.md}`, `threat_model/survivability_envelope.json` (byte-identical);
hashes in `protocol/FREEZE_G5.json`. Author chose:
1. Official attempt budget: at most THREE per variant (exp-h29-001..003, seeds 2921-2923); invalid runs repeat only by a new
   author decision on a new seed.
2. Envelope: "r3-draft-1" is the frozen H29 envelope; operational detail in spec/gate5/envelope-ops.json.
3. Workload excludes H25 governance-document actions (scope limit L4).
4. Safe progress 0.95 per fault class, post-recovery and per node, not only overall.
5. Lease-backed continuity (LEASE = 4 ticks) on the H29 path only; legacy authority path unchanged.
6. Catastrophic (out-of-envelope) boundary that does not fail explicitly -> REJECTED.
Upstream: H24 (G2), H27 (G2), H28 (G4 exp-h28-001r) SUPPORTED for both variants.
