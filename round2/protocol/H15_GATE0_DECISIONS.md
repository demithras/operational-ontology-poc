# H15 Gate 0 — orchestrator rulings on the Phase 1 protocol concerns

Made 2026-10-01, before any OpenPona encoding existed and before any H15 evidence. FREEZE.json is unchanged.
These rulings bind Phase 2 (OpenPona surface) and Phase 3 (experiment) exactly as written in
`ontology/h15_oracle_notes.md` (Gate-0 hashed); this file only records why they stand.

| # | Concern | Ruling |
|---|---|---|
| 1 | `constraint.scope` is unclassified by `sidecar_classification` | Treated as an opaque ATOM, as the IR schema types it (plain string, not a ref). The line must still declare that a constraint has a scope slot. |
| 2 | Effect `target`/`fields` are references for create/update/delete/link/unlink/git_change but opaque for `external_call` | Accepted. The operation is structure and must be in the line; the slot's interpretation follows from it. For non-external operations the target is part of the reference graph (line). |
| 3 | `<import>#<name>` qualified references are the oracle's own convention | Accepted as the Gate-0 convention; both surfaces are judged against it. |
| 4 | `auth:` / `policy:` prefixes in refs | Accepted. The prefix is the kind of the referenced resource = structure; a surface reconstructs it from the line's reference role, not from the record. |
| 5 | absent vs explicit null (`compensation_action`) | Accepted (strict). A surface that cannot distinguish them produces genuine non-equivalence. |
| 6 | empty-string atoms are legal where the schema allows | Accepted. Atoms live in the record, so an empty atom is representable by any surface whose record can hold "". |
| 7 | link cardinality orientation read off the frozen example | Accepted; applies identically to both surfaces. |
| 8 | IR limits found while deriving the real domains (single policy decision, non-Action compensation, Action context/evidence/closure) | Recorded as limits of the frozen IR, not of any surface. Candidate for a later IR version; out of scope for H15. |
| 9 | link endpoints / `{ref}` types may name interfaces | Accepted; the schema permits any string there and both surfaces are judged identically. |

Orchestrator verification of Gate 0 (independent of the builder's report): verify script re-run;
13 own probes on the oracle (order-significant inputs/effects, null vs absent, primary_key, authority
effect, cardinality, description, duplicate preconditions → non-equivalent; set reordering, resource
reordering, explicit defaults, property reordering → equivalent) all as expected; manufacturing
`transfer_inventory` cross-checked against contracts/actions/v3 and authorization/v2.
