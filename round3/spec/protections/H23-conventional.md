# H23 protections - conventional variant (typed service, policy engine, tool layer)

Paths are relative to `round3/src/conventional/`. Line numbers refer to the commit tagged `r3-p2b-conventional`.
Architecture: `variant.py` (Deployment) -> `tools.py` (tool surface, convenience layer) -> `service.py` (every entry point
authenticates, binds, authorizes, then commits inside ONE world transaction) -> `policy.py` (policy decision point),
`interp.py` + `helpers_*.py` (commit-time preconditions/business rules from the neutral ops spec), `effects.py` (writes via
`WorldHandle("conventional-service")`), `store.py` (idempotency + approval tables in the same SQLite file).

| Id | Where it lives | Mechanism |
|---|---|---|
| R1 identity binding | `service.py:88` (`authenticate`), `service.py:113-127` (`_execute`), `validation.py` (`validate_inputs`) | The acting subject is only the verified token `sub` (HMAC, expiry, audience `conventional`); request models are strict and generated, so identity-like fields in args are unknown fields -> INVALID, and `on_behalf_of` is a separate parameter checked by `policy.py:81` (`decide`: delegation entry AND delegable subject grant AND delegator allowed AND no deny). |
| R2 server-side backstop | `variant.py:23-26` (`direct`), `service.py:123` + `service.py:146-149` (`_txn`) | `direct` and `call_tool` both end in `Service.execute`, which re-authorizes (coarse gate, then resource-level PDP decision inside the transaction) regardless of what `tools()` showed; a hidden operation is refused by the PDP, not by absence. |
| R3 least exposure | `tools.py:25-31` (`visible`), `policy.py:136` (`exposed_operations`) | `tools(token)` lists operations for which the subject has a statically matching allow grant and no deny (delegation never adds operations: it requires the subject's own delegable grant). Reported as a measurement, not credited as protection. |
| R4 decision binding | `service.py:41-50` (`BoundRequest`, frozen, `MappingProxyType`), `validation.py` (single read of every caller key, JSON deep copy), `service.py:145-150` | The request is validated once into a deep copy; authorization, preconditions and effects all use that frozen copy plus the authority version in force; nothing the caller holds (its args object, returned bodies, `read` results via `copy.deepcopy` at `service.py:254,265`) can change what commits. `PolicyEngine` keeps its own copy of the authority spec (`policy.py:31`). |
| R5 replay and idempotency | `store.py:25-35` (`idem_get/idem_put`), `service.py:152-157` and `service.py:191-192` (`idem_put`) | Durable table `conv_idempotency(request_id, fingerprint, result)` written in the SAME transaction as the effects; consulted only AFTER the PDP decision, so a replay after `set_authority` (`service.py:73`) is decided against current grants; same id + different content -> INVALID; a refused attempt never burns the id. Whole `execute` runs under one lock + `BEGIN IMMEDIATE`, so concurrent duplicates commit once. |
| R6 commit-time preconditions | `service.py:163-171` (`_ctx` loads a fresh `WorldView` inside the transaction), `worldview.py`, `interp.py` | Preconditions and business rules are interpreted from the ops spec against the canonical world read inside the commit transaction (time from the injected clock); caller-supplied state is not an input. `exists` on a resource reference tests the world (`interp.py`, `exists` branch). |
| R7 explicit outcomes | `service.py:101-109` (`execute`), `service.py:139-143` (transaction), `effects.py` | DENIED = authentication/authority/business-rule/approval, INVALID = schema/precondition/effect conflict/idempotency-key misuse, UNAVAILABLE = dependency (`sqlite3.Error`, adapter marked down via `set_dependency_down`). Every non-OK outcome is an `_Abort`/exception inside `with h.transaction()`, which rolls back effects and idempotency rows together. |
| R8 legitimate progress | whole write path; `tests/conventional/test_functional.py`, `test_r5_r8.py::test_r8_*` | Every one of the 13 operations commits its specified effects for an authorized principal; approvals (`service.py:193` `_consume_approval`, `service.py:202` `approve`) are bound to the exact inputs and single-use. |

## Mutant switches (`r3_shared.mutants`; on only via `ConventionalVariant(mutants=[...])` / `load_variant("conventional", mutants=[...])`; frozen per instance, no global state)

| Switch | Where | Mechanism |
|---|---|---|
| `identity_substitution` | `service.py:117-121` | After token verification an identity-like args field (`principal`, `actor`, `owner`, `requested_by`, `subject`, `sub`, `user`) replaces the acting subject and is stripped so validation still passes. |
| `mutable_gated_input` | `service.py:159-164` | The commit stage re-parses the caller's original (mutable) args object instead of the frozen bound copy, so a value changed after authorization commits (resource set was authorized from the first read). |
| `backstop_bypass` | `variant.py:25-26` (`direct`) | `direct` calls the service with `_enforce=False`: no coarse gate and no PDP decision (authentication and schema validation remain); the tool surface path is unchanged. |
| `tool_overexposure` | `tools.py:29-30` | `visible()` returns every operation regardless of grants; the service backstop is unchanged, so effects stay zero and only the surface audit detects it. |

## Assumptions the neutral spec left open (report to orchestrator)
- Approvals: no approval input exists in the ops spec. Provided as `ConventionalDeployment.approve(token, operation, args, requester, on_behalf_of=None)` (protocol signature; single-use, exact-request binding); a `require_approval` rule without a bound, still-valid approval returns DENIED `approval_required` with zero effects.
- `on_behalf_of` business rules (`actor_holds` in `transfer-protected-route`) are evaluated for the delegator (effective principal), not the agent.
- `request_id=None` is accepted (no idempotency record); the operation spec says idempotency is "required", so a harness that wants replay protection must send ids.
- Delegate semantics (P1b): a principal with `delegated_by: P` is always evaluated as P's delegate (`policy.py:84-113`, `decide`), with or without `on_behalf_of`; `on_behalf_of != P` or a null delegator with `on_behalf_of` -> DENIED. `agent-orphan` is therefore denied everywhere; `exposed_operations` mirrors `authspec.allowed_operations` for delegates. Requests with and without `on_behalf_of=<delegator>` share one fingerprint (`policy.canonical_obo`).
- `request_id=None` stays accepted (no idempotency record, so no replay protection); the harness always sends ids.

## P5c rulings (2026-10-06)
| Ruling | Implementation | Test |
|---|---|---|
| R-1 numeric logical time | `helpers_proj.head_commit` compares integer ticks; non-integer -> helper_error INVALID | `test_p5c_rulings.py::test_r1_*` |
| R-2 optional ref existence (R6 target existence) | `service.py` `_txn`: supplied optional resource input must exist at commit, else INVALID `target_not_found`, zero effects | `test_r2_*` incl. sweep over every optional resource input of both domains |
| R-4 strict authority validation | `authspec.validate_strict(spec, ops)` on deploy and every `set_authority`; ValueError, version unchanged | `test_r4_*` (duplicate grant id, schema-invalid origin, dangling principal) |

## P7b - A8 crash, restart and concurrency (PROT-H23-A8)

| Req | Conventional mechanism | Test |
|---|---|---|
| R9 crash safety | Effects, the idempotency ledger row and approvals commit in ONE world transaction (`service.py` `_execute`), so a `before_commit` crash (raised inside the open transaction, after authorization/validation, before `effects.apply`) rolls back to zero effects, and an `after_commit` crash (after the transaction closes, before the reply) leaves exactly that request's effects AND its durable ledger row. `restart()` rebuilds the policy from the durable `conv_authority` row (`store.authority_put/get`); nothing else is held in memory. A same-`request_id` replay after restart returns the stored result (`replayed: true`), zero new effects; a new `request_id` is decided afresh against current authority and preconditions. | `tests/conventional/test_a8_crash.py` |
| R10 concurrency safety | One `RLock` serialises authorize -> commit across `execute/approve/read/set_authority`; the commit also runs in `BEGIN IMMEDIATE`, with preconditions read inside it. | `tests/conventional/test_a8_concurrency.py` (8 threads: same request_id -> one effect set; conflicting `supersede_hypothesis` races -> final world equals one of the two hand-written serial outcomes) |

Design notes: `state_dir` is accepted but unused (all durable state lives in the world DB, atomic with the effects). The armed crash is
consumed only by a request that reaches the commit point (a denied/invalid request does not trigger it). While crashed, `tools()` is
empty and every other call returns `UNAVAILABLE {"reason": "crashed"}`. A crashed `set_authority` raises RuntimeError.

New mutant switches (`r3_shared.mutants`):
- `ledger_after_commit_volatile`: the committed-request record is kept in a memory dict written only after the after_commit crash point; a crash + replay double-commits (`test_mutant_ledger_after_commit_volatile_double_commits_on_replay`; control: without a crash it still replays).
- `unsynchronized_commit`: no lock and no world transaction around the authorize -> commit section, plus a 50 ms window between the precondition read and the write (mutant-only sleep, makes the race deterministic). Same-id races double-commit; conflicting supersedes commit non-serial states (`test_mutant_unsynchronized_commit_*`).

Audit items (P6): (a) FIXED - `PolicyEngine.exposed_operations` now requires the delegation entry to list the operation, matching `decide()`
(`test_a8_audit.py`). (b) `request_id=None` is still accepted and has NO replay protection (documented in `service.py`; unchanged by decision).
