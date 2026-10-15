# 07 — Safe continuity model

Paladin's class intuition is to keep an operation going under hostile conditions. A literal "any conditions" claim is neither testable nor physically meaningful.

Round 3 therefore freezes `threat_model/survivability_envelope.json`.

For each operation during a fault, the independent dependency oracle classifies it as:

```text
SAFE_TO_RUN
BLOCKED_BY_DEPENDENCY
UNRESOLVED
```

The candidate gets no credit for safety by globally stopping all work. H29 measures:

- safety violations;
- safe-progress ratio for operations whose required dependencies remain available;
- explicit dependency-unavailable classification;
- deterministic state reconstruction after recovery.

Catastrophic loss of all trust roots is a boundary condition and should produce explicit inability to establish legitimacy, not simulated resilience.
