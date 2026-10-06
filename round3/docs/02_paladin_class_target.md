# 02 — Operational definition of Paladin-class

Round 2 used a Palantir-class capability target: Language × Engine × Toolchain over Data × Logic × Action × Security.

Round 3 adds a stronger operational class. A system is **Paladin-class in this experiment** only if the shared executable contract and runtime establish all six invariants:

| Invariant | Meaning |
|---|---|
| P1 Authority integrity | Effects derive from legitimate, current, scoped authority. |
| P2 Effect containment | Compromise cannot exceed issued effect capability. |
| P3 Knowledge sovereignty | Protected knowledge does not escape disclosure authority through supported surfaces. |
| P4 Provenance integrity | Historical justification is version-pinned and tamper-evident. |
| P5 External truth | Intent/command is not confused with observed outcome. |
| P6 Safe continuity | Bounded faults preserve safety, useful safe progress and deterministic recovery. |

Paladin is therefore not "Palantir plus more security products." It is a claim about the **composition** of authority, knowledge, action, truth and survival semantics.

H23-H29 test the parts. H30 tests whether that composition creates material value against a fair conventional alternative.
