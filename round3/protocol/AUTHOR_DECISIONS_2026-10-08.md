# Author decisions - Gate 3 (H25 + H26) design freeze (2026-10-08)

Frozen before any Gate 3 implementation: `spec/protections/PROT-H25.md`, `spec/protections/PROT-H26.md`,
`spec/gate3/{PROTOCOL-P1e.md,ORACLE-AND-HARNESS-G3.md,EQUIVALENCE-G3.md,OPEN-QUESTIONS.md}`; hashes in
`protocol/FREEZE_G3.json`. Author chose (designer recommendations accepted):
1. H25 domain branches: governance policies expressed as DATA are allowed for both variants; per-domain/per-model
   decision CODE counts as a domain_privilege_branch for both. Primary audit: a consistent renaming test (identical
   outcomes under renamed principal/body/model ids); a static scan is secondary.
2. H26 visibility logic is NOT shared code: each variant implements sovereignty itself; only frozen forms and the
   tool_schema derivation are shared; an early oracle-vs-variant conformance test catches disagreements.
3. H26 declared low facts D1-D4 accepted. Recorded scope limits: activity volume (transaction counters) is not protected;
   outcomes of authorised writes are declassified (D4); provenance chain fields are auditor-only, so Round 3 has no
   principal-verifiable redacted chain.
4. Definitions and floors accepted as written: three structurally distinct governance models (hierarchical, collegial,
   polycentric); H25 floors (PROT-H25 s7); H26 floors (PROT-H26 s9); no principal-facing case-status API in Gate 3.
