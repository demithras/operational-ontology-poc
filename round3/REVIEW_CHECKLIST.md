# Author review checklist before Round 3 protocol freeze

- [x] Round 2 upstream pin `8f9ff26...` is still the intended evidence base.
- [x] H22/H22w remain rejected and are not being silently reopened under a new name.
- [x] The six Paladin invariants P1-P6 match the intended class definition.
- [x] The attack classes A1-A10 are strong enough and the explicit out-of-scope boundary is acceptable.
- [x] The survivability envelope is realistic and does not make H29 trivially green.
- [x] H23 attacks both generated surfaces and Engine backstop; tool hiding alone cannot earn support.
- [x] H24 revocation boundary/clock semantics are frozen before concurrency evidence.
- [x] H25 preserves the procedural-authority vs discretionary-content boundary.
- [x] H26 application-layer noninterference scope is acceptable; timing/hardware/model-memorization channels are explicitly excluded.
- [x] H27 has a genuinely independent integrity anchor; the mutable candidate store cannot rewrite its own oracle.
- [x] H28 action and observation paths are meaningfully independent.
- [x] H29 safe progress is measured only for operations whose frozen dependencies remain available.
- [x] H30 baseline receives equivalent best-practice hardening, code generation, cryptography, isolation, provenance and reconciliation.
- [x] Review H30's material-advantage thresholds: 0.50 blast-radius ratio, 0.67 containment/recovery-cost ratio, <=5pp safe-progress regression, <=2x p95 latency, <=2.5x recurring security machinery.
- [x] Every H23-H29 major falsifier has at least one planted mutation that must be detected.
- [x] Only after review: run `make check`, `make freeze`, commit `protocol/FREEZE.json`, and then begin implementation/evidence generation.

Reviewed by the author 2026-10-06; decisions in `protocol/AUTHOR_DECISIONS_2026-10-06.md`.
