# Round 4 hypotheses

This round contains H31-H37. H31 and H32 test coordination of AI agents across projects. H33, H34 and H35 test control of what agents may do and what counts as true. H37 tests access grants to agents (least privilege, expiry, revocation, no self-grant). H36 is the only comparative-value claim.

Authoritative claims and evaluator conditions live in each `contract.json`; README files are generated human-readable views.

Every contract names the conventional stack as a rival. Parity with the conventional stack is a reject for H36, and for H31-H35 and H37 it is recorded as "no advantage measured".

Every comparative bar is read through `thresholds.headroom_rule`: above a baseline rate of 0.80 the treatment must close at least half of the baseline's misses, and at 0.95 or more the class is recorded as CEILING (INCONCLUSIVE with reason "CEILING"), never REJECTED.
