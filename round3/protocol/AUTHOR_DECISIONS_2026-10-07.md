# Author decisions after the first official H23 run (2026-10-07)

Made after exp-h23-001 was revealed. Recorded as post-reveal; no evidence file is edited.

## 1. exp-h23-001 stands as REJECTED for both variants; the fix goes into a new candidate version

exp-h23-001 rejected both variants on one shared cause: a delegate's approval given with one `on_behalf_of` form was
consumed by a commit sent with the other form (null vs the delegate's own delegator). The oracle follows the protocol
text (approvals bind the exact `on_behalf_of`); both variants followed a contradictory orchestrator instruction. See
`experiments/h23/exp-h23-001/ATTRIBUTION.md`.

Author chose: keep the verdict; do not change the oracle; tighten both variants to the protocol text; new candidate
version; re-measure as exp-h23-002 with a new seed. PROT-H23 is clarified accordingly (approval binding paragraph).

## 2. Gate 2 (H24 + H27) design freeze

Frozen before any Gate 2 implementation: `spec/protections/PROT-H24.md`, `spec/protections/PROT-H27.md`,
`spec/gate2/PROTOCOL-P1d.md`, `spec/gate2/ORACLE-AND-HARNESS-G2.md`, `spec/gate2/EQUIVALENCE-G2.md`; rulings in
`spec/gate2/OPEN-QUESTIONS.md`. Author chose:
a. H27 anchor enforcement: the harness+variant process runs under macOS sandbox-exec denying writes to the anchor
   directory; the anchor is a separate OS process with its own key; its log is an HMAC hash chain whose key is revealed
   at close (no new dependency).
b. H24 safe-progress floors (not in thresholds.json; frozen in PROT-H24 s8): unaffected legitimate progress 1.0,
   race overlap >= 0.50, >= 1 effect-first order; any unmet floor -> the variant cannot be SUPPORTED.
c. H27 counting: >= 5,000 tampered cases from >= 600 distinct base histories in both domains + >= 1,000 clean
   controls; bound evidence = resource inputs + `newest` terms; business-rule replay is out of scope and recorded.
d. Stop rule: each gate records two verdicts and continues; downstream gates stop only if BOTH variants reject.
