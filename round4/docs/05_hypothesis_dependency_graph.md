# 05 Hypothesis dependency graph

```text
        COORDINATION                           CONTROL
   ┌────────────────────┐        ┌───────────────────────────────────────┐
   │ H31 leases         │        │ H33 control gate   (K1-K3; F5-F10)    │
   │ (C1, C2; F1, F2)   │        │ H34 external truth (K4; F4)           │
   │ H32 cross-repo     │        │ H35 provenance     (K5)               │
   │ blockers (C3; F3)  │        │ H37 access grants  (K6-K8; F11-F15)   │
   └─────────┬──────────┘        └──────────────────┬────────────────────┘
             │                                      │
             └──────────────────┬───────────────────┘
                                ▼
                    H36 total value (cost and benefit frontier)
```

## Rules

1. H31-H35 and H37 are independent of each other; each can end at parity or ceiling without stopping the others.
2. H36 depends on all of H31-H35 and H37 and may not be called SUPPORTED just because they are green. It needs a cost and benefit frontier and a surviving fairness audit.
3. A hypothesis that ends INVALID blocks H36 for the classes it covers (H36 becomes INCONCLUSIVE).
4. If every H31-H35 and H37 result is "no advantage measured" in the pilot, the round stops at the pilot and H36 is recorded as REJECTED for the tested scope.

## Upstream links to Round 3

| Round 4 | Round 3 prerequisite | Role |
|---|---|---|
| H31 | H24 | expiring and revocable grants |
| H33 | H23, H24 | effect containment, delegation and revocation |
| H34 | H28 | adapter boundary: the action path is not the truth oracle |
| H35 | H27 | tamper-evident provenance |
| H37 | H23, H24, H28 | containment, revocation and expiry, observer outside the action path |
| H32 | none | new in Round 4 |

## Expected strength

| Hypothesis | Expectation | Why |
|---|---|---|
| H34 | strongest | agents' self-reported success is unreliable even without an adversary |
| H33 | at risk of parity (H11 pattern) | branch protection, CODEOWNERS and required checks already cover much of F5-F8 |
| H37 | at risk of parity | Vault dynamic credentials with TTL and IAM conditions are a mature category |
| H31, H32, H35 | open | depends on how well the baseline script is built |
| H36 | hardest | parity is REJECTED; cost counts |
