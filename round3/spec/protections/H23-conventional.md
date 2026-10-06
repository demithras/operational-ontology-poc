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
