# Author decisions before the Round 3 freeze (2026-10-06)

Made during author review of the pack (REVIEW_CHECKLIST.md), before any Round 3 implementation or evidence.

## 1. Dual track: a strong conventional implementation runs in parallel with Paladin

Author: "Maintain a strong conventional implementation in parallel with Paladin throughout Round 3. Both variants must
satisfy the same operational requirements, attacks, oracles, and quality bar. Whenever Paladin gets a new protection,
give the conventional baseline the strongest reasonable conventional equivalent. Paladin-specific value counts only if
it still shows a measurable advantage under this fair comparison. If Paladin fails, the conventional implementation
remains the viable product path."

Encoded in `protocol/DUAL_TRACK.json` (frozen). Consequences:
- Each H23-H29 gate issues **two verdicts** (Paladin, conventional) from the same corpus and evaluator, plus a
  comparative record. The value verdict remains H30's alone.
- The conventional variant is built by a **separate builder agent** from the protection specification, never from
  Paladin source; low-level libraries are shared. An independent reviewer audits equivalence before each gate.
- Pairing is tracked in `protocol/HARDENING_LEDGER.jsonl`.

## 2. H27 depends on H19 + H23, not H25

The contract listed H19 + H25 while `docs/10` (Gate 2) and `docs/12` placed H27 after H23 next to H24. Provenance
integrity does not need the constitutional authority model. The contract is amended to `["H19", "H23"]`; H27 runs in
Gate 2.

## 3. H30 blind tasks come from employer material

The >=40 blind realistic tasks are derived from employer operational/security change material. The corpus and its raw
evidence live only on the never-pushed branch `round3-h30-private`; the public branch receives aggregates only (same
regime as Round 2 H22).

## 4. Trust split (orchestrator design, accepted by default)

- H27 integrity anchor: a separate signer process with its own key; anchor roots are written to a directory neither
  variant's process can write. Both variants receive the same anchor class.
- H28 observation path: the observer reads the external effect ledger directly and never consumes the action adapter's
  response.

## 5. Execution and publication

All gates run continuously; stop only on a fired preregistered falsifier, a contaminated oracle, a failed fairness
audit or a pack stop condition. H23-H29 are public on branch `round3`. Thresholds in `protocol/thresholds.json` are
frozen unchanged.
