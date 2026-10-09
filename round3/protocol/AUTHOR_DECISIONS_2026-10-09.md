# Author decisions - Gate 4 (H28) design freeze (2026-10-09)

Frozen before any Gate 4 implementation: `spec/protections/PROT-H28.md`, `spec/gate4/{PROTOCOL-P1f.md,
ORACLE-AND-HARNESS-G4.md,EQUIVALENCE-G4.md,OPEN-QUESTIONS.md}`; hashes in `protocol/FREEZE_G4.json`. Author chose:
1. Official attempt budget: at most THREE per variant (exp-h28-001..003), declared before any run; the last attempt run is
   final; harness/launch-invalid runs do not count and are repeated only by a new author decision.
2. Project domain: an H28-only overlay with two external operations (publish_result, notify_reviewer); base specs untouched.
3. Stop rule tested, not only declared: frozen observability levels (WMS/ERP full, MES effects-only) plus one generated
   system per domain without any observation path, whose effects must stay UNKNOWN.
4. Scope limit L1: the observer (truth source) is not attacked; only unavailable/lagging observer faults are injected.
Also (by the author's Gate 2/3 precedents): the outcome function is not shared code; non-falsifier floors as drafted.
