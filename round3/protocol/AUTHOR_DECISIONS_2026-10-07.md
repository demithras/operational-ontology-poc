# Author decisions after the first official H23 run (2026-10-07)

Made after exp-h23-001 was revealed. Recorded as post-reveal; no evidence file is edited.

## 1. exp-h23-001 stands as REJECTED for both variants; the fix goes into a new candidate version

exp-h23-001 rejected both variants on one shared cause: a delegate's approval given with one `on_behalf_of` form was
consumed by a commit sent with the other form (null vs the delegate's own delegator). The oracle follows the protocol
text (approvals bind the exact `on_behalf_of`); both variants followed a contradictory orchestrator instruction. See
`experiments/h23/exp-h23-001/ATTRIBUTION.md`.

Author chose: keep the verdict; do not change the oracle; tighten both variants to the protocol text; new candidate
version; re-measure as exp-h23-002 with a new seed. PROT-H23 is clarified accordingly (approval binding paragraph).
