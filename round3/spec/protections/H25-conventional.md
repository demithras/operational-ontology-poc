# H25 protections - conventional variant (constitutional authority topology, PROT-H25)

Paths relative to `round3/src/conventional/`; line numbers at the commit tagged `r3-g3-conventional` (src files are not
edited after the doc is written). Policy is DATA: the `r3-governance-1` document is evaluated by ONE generic procedure
(`govproc.py`); the service (`govsvc.py`) is the case/judgment/emergency store. No per-domain, per-model, per-body or
per-principal decision code exists (author decision 1, Q1). Case state is event-sourced: the committed `governance`
marks are the authoritative order/time, `govstore.py` holds what a frozen mark cannot carry (request ids, args).

| Id | Where | Mechanism |
|---|---|---|
| R25-1 procedural equality | `govsvc.py:103` (`constitutional`), `govsvc.py:131` (`_gtx`), `govsvc.py:149-346` (`_g_*`) | One entry point; token -> request_id/schema (`r3_shared.constitutional.check_action`) -> `no_governance` -> action handler whose checks are written in the exact order of PROT-H25 s3.1-3.5; refusal bodies are `{reason}` only (`K.refusal_body`); ONE transaction (`tag="governance"`) and ONE mark built by `K.governance_mark` per OK action; a refusal raises `_Abort` and the transaction rolls back (zero writes). |
| R25-2 no effect without legitimacy | `service.py:381-382` (`_txn` gate), `govsvc.py:229` (`_g_execute`), `govsvc.py:275` (`_g_act`) | A request covered by a matter can only commit via `execute` (final ALLOW at THIS commit, base authority re-decided at THIS commit, then the unchanged H23 `_txn`) or `act` (ACTIVE emergency). Plain `call_tool`/`direct` of a governed request -> DENIED `case_required` AFTER the base-authority check (no fallback to base authority). |
| R25-3 no fabricated judgment | `govproc.py:154` (`_body_outcome`), `govproc.py:169` (`_stage`), `govproc.py:196` (`decision`) | The procedure consumes `(judge, value)` only; `merit` never leaves `govsvc._g_judge` (mark carries `merit_digest`, journal stores it). AWAITING stays AWAITING (`oracle_needed`); the only non-judged outcome is the document-declared lapse (`govproc.py:196-204`, basis `()`, rule `lapse`). Counted judgment = first valid judge action per eligible member (`govproc.py:176-181`). |
| R25-4 bounded emergency | `govsvc.py:177` (`_check_declare`), `govsvc.py:267` (`_emergency`), `govsvc.py:275` (`_g_act`), `govsvc.py:322` (`_g_end`) | Declare = a case on the emergency matter; ceiling/duration/grantee checks at propose; ACTIVE is DERIVED from the case's final ALLOW and the absence of an `end` mark; `act` checks grantee, scope coverage (`scope_covers`), strict expiry (`tick >= expires_at`), deny grants, then runs the H23 operation with `gate=False`, `pre=` decision. Nothing is written to the authority document, so nothing survives expiry/end (no residual); edges never derive from it. |
| R25-5 explicit unresolved | `govproc.py:97` (`route` -> `precedence_unresolved`), `govsvc.py:236-246` | `oracle_needed`, `not_final`, `precedence_unresolved`, `case_denied` are refusals with zero effects. |
| R25-6 genericity | whole `govproc.py` | Body/matter/principal ids appear only as data; `tests/conventional/test_conv_g3_h25.py::test_r25_6_*` runs all 6 fixtures and a consistent-renaming test. The only literal comparisons are protocol vocabulary (`"quorum"`, `"single"`, `"requester"`, `"rank"`, `"superior"`, `"specialis"`). |
| R25-7 durability/replay | `govbook.py:17` (`refold`), `govsvc.py:50` (`_gov_restore`), `govsvc.py:135` (idempotency via `CaseBook.by_rid`) | After `restart()` the book is re-folded from committed marks + journal; the governance document is the last `set_governance` blob (else the deployed one); `request_id` replays return the stored result; same id with another action -> INVALID `idempotency_key_reuse`. `arm_crash` handled in `_gtx` (before: rollback; after: result lost, state kept). |
| R25-8 safe progress | one lock (`service.py` `_lock`) serialises every constitutional action with effect commits | No UNAVAILABLE on contention; linearisation = world_log order. |

## Decision rules where the frozen text needed an interpretation (reported)
1. Lapse is fixed at the FIRST committed transaction carrying a mark with `tick >= propose_tick + after` (`govsvc.py:60`, `_first_tx`; the transaction being committed counts). Review windows of a lapsed decision count from that tick.
2. `specialis` (`govproc.py:118`): a body is dropped iff EVERY matter it is competent in is a strict superset of another covering matter naming a different body.
3. Governing matter of a case (review/lapse source) = first covering matter, in document order, that names a deciding body.
4. `end`: unknown/ended emergency -> DENIED `emergency_inactive`; caller not in a deciding body -> DENIED `not_grantee`. `execute` of an `emergency:declare` case writes the execute mark and no canonical effect.
5. `act` with an operation/args that fail the request schema -> the H23 INVALID reason (after the emergency checks).

## Mutant sites
| Mutant | Site | Bug |
|---|---|---|
| `precedence_inverted` | `govproc.py:119` (`_keep`, `inv`) | each criterion keeps the MINIMAL elements. |
| `quorum_weakened` | `govproc.py:160-161` (`_body_outcome`, `weak`) | a quorum body allows at k-1 concurring judgments. |
| `emergency_no_expiry` | `govsvc.py:286` (`_g_act`) and `govsvc.py:314` (`emergency_ops`) | `expires_at` ignored (`end` still works). |
| `merit_autofill` | `govproc.py:216`, `:229` (`final`) | AWAITING decision/review stage at execute -> ALLOW with basis `autofill:<case>`. |
| `domain_privilege_branch` | `service.py:352` (`_case_exempt`) | project domain + requester id ending `-1` skips `case_required` (a domain/identity branch in the decision path; audit target). |
