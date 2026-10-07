# H24 protections - Paladin variant (protection spec: spec/protections/PROT-H24.md)

Where each H24 requirement and mutant lives in the Paladin variant (`file:line`, one sentence). Lines refer to the commit tagged
`r3-g2-paladin`. Shape ("Paladin-shaped", EQUIVALENCE-G2): capabilities are VERSION-BOUND authority objects of the control plane:
every edge lives in the authority document whose digest is `authority_version()`; each delegate/revoke/set_authority yields a new
document and a new version, the Engine's authority gate decides the root's base authority (PROT-H24 s3 (e)) and the path rule
(`capgraph.py`) decides (a)-(d),(f) inside the commit transaction. No vendored Engine/Toolchain file changed in Gate 2.

Architecture delta over H23: every effect commit is ONE world write transaction on the handle that owns the operation's effects
(src/paladin/core.py:283, `th.transaction(tag="effect")`; project -> service handle, manufacturing -> the single external system's
handle, chosen at src/paladin/core_g2.py:44) holding the edge-path check, the evidence read, the Engine pipeline, the adapters' writes
and the `commit` mark (src/paladin/core.py:300). Every authority mutation is ONE service-handle transaction with its `authority` mark
(src/paladin/core_g2.py:198) and a `commit` mark (src/paladin/core_g2.py:200). Time is only `tx.tick`.

## Requirements R24-1 .. R24-7

| Id | Where it lives | Mechanism |
|---|---|---|
| R24-1 attenuation | src/paladin/capgraph.py:101 (`check_issue`), src/paladin/capgraph.py:132-137, src/paladin/capgraph.py:188 (`find_path`) | Issuance evaluates PROT-H24 s2 in order inside the delegate transaction (scope subset via `r3_shared.authgraph.scope_subset`, expiry non-amplification, root edge needs a delegable allow grant matching the issuer); use evaluates the intersection of EVERY edge's scope on the path (`scope_covers` per edge). |
| R24-2 freshness | src/paladin/core.py:283-290 (`edge_check` inside the effect transaction), src/paladin/capgraph.py:82 (`path_valid`), src/paladin/core_g2.py:126 | Path validity (revoked / strict expiry / scope / deny on subject and issuers) is decided at `tx.tick` inside the commit transaction against the document in force; the root's base authority is the Engine authority gate of the same pipeline run, which sees the spec installed by `set_authority`. |
| R24-3 linearizable boundary | src/paladin/core_g2.py:181-219 (`apply_authority`), src/paladin/core.py:183-228 (`run`), src/paladin/core_g2.py:63 | Revoke/delegate/set_authority/effect all take the deployment lock and one world write transaction; the revocation is persisted and applied before the transaction commits and before OK is returned, so any later-invoked call sees it and the world_log order is the real-time order. |
| R24-4 explicit conflict | src/paladin/capgraph.py:101-147 (reason codes of PROT-H24 s2), src/paladin/core.py:145-170 (`principal`), src/paladin/core_g2.py:126-147 | Every refusal returns its named reason and rolls the transaction back (zero world rows); a non-delegate naming `on_behalf_of` is ONLY evaluated as an edge request: no path -> DENIED `no_valid_path`, never a fallback to the subject's own or the root's base authority. |
| R24-5 durability | src/paladin/core_g2.py:62-66 (`persist`), src/paladin/core_g2.py:204-207, src/paladin/core.py:92-100 | The new authority document and the request's COMMITTED ledger row are written (SQLite synchronous=FULL ledger, or the HistoryStore) inside the transaction before it commits; `before_commit` fires after the marks but inside the transaction (rolled back = absent), `after_commit` fires after the commit (edge stays revoked); the document in force is reloaded on restart. |
| R24-6 historical authority | src/paladin/core.py:303 (`used:<rid>` meta), src/paladin/deployment.py:285 (`authority_used`) | The version, commit-mark seq, `tx.tick` and edge path of every committed request are recorded durably with the request; the answer is read from that record and never recomputed against the current document. |
| R24-7 safe progress | src/paladin/core.py:183 (`run` holds the lock only for decide+commit) | A revoke in one subtree takes the same short lock/transaction as any commit; no request is refused UNAVAILABLE because of an unrelated revocation (tests: 4 unaffected legit requests race a revoke, all OK). |

## Mutants (constructor-activated, frozen names)

| Mutant | Site | Effect |
|---|---|---|
| non_attenuating_delegation | issuance: src/paladin/capgraph.py:132 (subset/expiry checks skipped); use: src/paladin/capgraph.py:192 (only the last edge's scope) | amplified edge accepted and used outside the parent's scope |
| stale_authority_cache | src/paladin/core_g2.py:129 and :141 (`_dcache`, keyed by (subject, obo, op, resources) WITHOUT the authority version, never invalidated) | a decision made before a revoke/expiry/set_authority is reused after it. The correct build's cache (src/paladin/core_g2.py:118, `candidates`) is keyed by authority version and caches only structure; validity is re-checked per request. |
| revoke_commit_reorder | src/paladin/core_g2.py:173 (acknowledge, queue) and :222 (`flush_deferred`, applied after the next effect commit, called at src/paladin/core.py:222) | OK returned before the commit point; an effect commits between the ack and the revoke |
| expiry_inclusive | src/paladin/capgraph.py:85 (`tick <= expires_at`) | edge usable at tick == expires_at |

## Tests
tests/paladin/test_pal_g2_h24.py (one test per R24-n + tool-surface), tests/paladin/test_pal_g2_mutants_h24.py (each mutant: clean
build vs mutant on the same scenario), tests/paladin/test_pal_g2_project.py (second domain, approval-chain exclusion).

## Known limits (stated, not hidden)
- Authority durability is "durable before the world commit completes": a process death strictly between the durable write and the
  world COMMIT is not recoverable by the variant (the harness's two crash points - before_commit, after_commit - do not hit it; the
  world store exposes no read of world_log to the variant to reconcile it). An in-process failure of the COMMIT undoes the write.
- Variant reads of its own world_log head / transaction rows use the handle's SQLite connection (worldbridge.log_head / tx_rows):
  the handle has no accessor (reported as a missing capability, not a bug).

## G2 fix1 (E-5)
- `set_authority` replaces the BASE layer only. When the authority in force is v2 and has edges/revocations (or the supplied document
  is itself v2), `Core.replace_authority` re-attaches the in-force `capabilities` and `revoked` (and the in-force depth when the document
  omits it) before validation; `capabilities`/`revoked` in the document are ignored. No un-revoke by any path.
  Tests: tests/paladin/test_pal_g2_fix1.py::test_e5_*.
