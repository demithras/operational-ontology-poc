# H24 protections - conventional variant (versioned delegation table + PDP re-check at the commit point)

Paths relative to `round3/src/conventional/`; line numbers at the commit tagged `r3-g2-conventional`. Design: tokens carry
IDENTITY ONLY; authority is re-derived from the delegation table (the v2 authority document) inside the commit transaction
(EQUIVALENCE-G2 'conventional', no token-scoped authority).

| Id | Where | Mechanism |
|---|---|---|
| R24-1 attenuation | `authdoc.py:72` (`check_issue`, steps 2-6 of PROT-H24 s2), `pdp.py:41` (`valid_path` (d): `authdoc.in_every_scope`) | Issuance refuses a non-root edge whose scope is not a syntactic subset (`scope_subset`) or whose expiry exceeds the parent's effective expiry; a root edge needs a delegable allow grant covering every operation (`pdp.py:22`). Use intersects EVERY edge scope on the path. |
| R24-2 freshness | `pdp.py:41` (a)(b)(c)(e)(f), `authdoc.py:57` (`path_valid`), `service.py:278` (`_decide`) called with `tx.tick` inside the effect transaction | Root must be the `on_behalf_of`; every edge un-revoked and `tick < expires_at`; Q's base authority re-evaluated against the table in force; no deny grant on subject or any issuer. The decision cache key includes (version, digest, tick). |
| R24-3 linearizable boundary | `service.py:192` (`execute` under one `RLock`), `authority_ops.py:104` (`_mutation_tx`, tag `authority`), `service.py:356` (`commit` mark) | Delegate/revoke/set_authority and every effect commit are single world transactions taken under the service lock, so the world_log order is the real-time order of non-overlapping calls. The authority mark and the `commit` mark share the revoke's transaction; OK is returned only after it commits. |
| R24-4 explicit conflict | `authdoc.py:72`, `authdoc.py:31` (`edge_schema_ok`), `authority_ops.py:46` (`_plan_delegate`), `pdp.py:29` (`decide`) | Cycle / unknown parent / static delegate / depth / duplicate / wrong holder return the named reason with the transaction rolled back. `decide` never falls back to base authority when `on_behalf_of` is set (`no_valid_path`). |
| R24-5 durability | `authority_ops.py:129` (`_apply_mutation`), `store.py` (`authority_put`, same transaction) / `histledger.py:94,100`, `service.py:138` (`restart`) | The table version is written in the revoke's own world transaction (aux table, or a digest-addressed blob + the `authority` mark's `version` when a HistoryStore is used); restart rebuilds the PDP from it. `before_commit` crash rolls the open transaction back; `after_commit` leaves it committed. |
| R24-6 historical authority | `authority_ops.py:158` (`authority_used`), `service.py:356` (`idem_put(... used ...)` record) | The idempotency record keeps {authority digest, path, on_behalf_of}; seq/tick come from the request's `commit` mark. Reading it never re-evaluates the path. |
| R24-7 safe progress | `service.py:192` | A revoke holds the lock only for its own short transaction; an unrelated request is never refused (no blocking on revocation). `test_r24_7_*` runs 6 threads against a revoke. |

Marks (PROTOCOL-P1d errata E-1): `authority` `{op, edge|edge_id, version}` and `commit` `{request_id, kind, authority_version}` are written in the same transaction (`authority_ops.py:134-135`, `service.py:356`). `version` = sha256 of the canonical v2 document after the mutation (`authgraph.authority_digest`).
An already-revoked edge writes the `commit` mark and the idempotency record but NO `authority` mark (PROT-H24 s5).

## Mutant sites (constructor-activated; `ConventionalVariant(mutants=[...])`)

| Mutant | Site | Bug |
|---|---|---|
| `non_attenuating_delegation` | `authority_ops.py:56` (issuance skip) and `pdp.py:50` (`last_only`) | `check_issue(skip_attenuation=True)`; `in_every_scope(last_only=True)` evaluates the last edge's scope only. |
| `stale_authority_cache` | `service.py:278-297` (`_decide`, the PDP decision cache) | key = (subject, obo, op, resources) without version/digest/tick, never invalidated; the cached Decision's version is not compared. |
| `revoke_commit_reorder` | `authority_ops.py:121` + `service.py:265` (`_drain_pending`) | revoke validates, returns OK and queues; the revocation (mark, commit mark) is applied after the NEXT effect commit. |
| `expiry_inclusive` | `pdp.py:48` -> `authdoc.py:57` (`inclusive_expiry`) | an edge is valid while `tick <= expires_at`. |
