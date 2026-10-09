# H28 protections - conventional variant (Byzantine adapters are neither authorities nor truth oracles, PROT-H28)

Paths relative to `round3/src/conventional/`. Architecture (EQUIVALENCE-G4 'conventional'): transactional outbox written in the
request's world transaction, a post-commit dispatcher, a reconciler that reads ONLY the ObservationClient, and per-effect
least-privilege capabilities minted by attenuating the deployment's root cap (token-exchange style). Adapter-side code
(`ADAPTER_MODULES` = `conventional.extout`, `conventional.extrecon`) imports no authority/policy/approval/governance/disclosure module.
Only P1f forms, caps crypto, ExternalWorld and the ObservationClient come from `r3_shared`; the outcome function is implemented here.

| Id | Where | Mechanism |
|---|---|---|
| Seam (P1f-1) | `variant.py` `deploy(external=)`, `service.py` `__init__` (`self._ext`), `service.py` `_txn` (ext split), `effects.py` untouched | `external=None` keeps the legacy `WorldHandle.external_write` path byte-for-byte; with a binding the `external` effects are filtered OUT of `effects.apply` (zero `external_effects` rows) and enqueued. |
| R28-1 decide before dispatch | `service.py` `_txn` (enqueue inside the world tx), `service.py` `execute` -> `extsvc.py` `_post_commit` | status/reason/effects/envelope are fixed by `_provenance` BEFORE `_post_commit`; dispatch exceptions are swallowed; the OK body only gains `outcomes`. |
| R28-2 no adapter authority | `extout.py` `dispatch` (reply -> `status` string only), `extrecon.py` | the reply is reduced to its `status` and decides resubmission only; no module of the decision plane is importable from adapter-side code (`test_conv_g4_audit.py`). |
| R28-3 generic enforcement | `service.py` `_txn` (deny rules / preconditions / approvals over ops-spec data) | unchanged generic engine; `policy_gate_in_adapter` is the only place a rule moves (mutant-guarded). |
| R28-4 vocabulary | `extout.py` DDL `conv_outcome`, `extrecon.py` `initial_state`; `outcome.validate_outcome` on every body (test) | one record per (request_id, effect_index), written in the commit tx: PENDING (UNKNOWN/low for `none`). |
| R28-5 outcome function | `extrecon.py` `outcome_state` | N, U, D1, D2, D3, S, F, W in the frozen order; class/observability/expiry from the stored intent (systems.json data), no per-system names. |
| R28-6 monotone safety | `extrecon.py` `next_state`; DDL trigger `conv_outcome_monotone` | RECONCILED_* moves only to DIVERGED, enforced in code AND by a DB trigger. |
| R28-7/8 idempotency | `extout.py` `enqueue` (max_uses 1 / 3), `dispatch` (same stored cap, `MAX_ATTEMPTS=3`, `_settled`, expiry) | Stripe-style: the cap is stored with the intent; retries reuse it; a replayed request_id never reaches `dispatch` (replay path returns before enqueue). |
| R28-9 observation path | `extrecon.py` `read_snapshot` / `reconcile`; `extsvc.py` `reconcile` | `observer.read(watermark)` only; ObserverUnavailable -> rule U (OK, never an error). |
| R28-10 observability | `extrecon.py` `confidence_for`, `outcome_state` rule N | read from `systems["systems"][S]["observability"]`; `none` is UNKNOWN/low for ever. |
| R28-13 attenuation | `extout.py` `_caveats` / `enqueue` | system, operation, target (rendered from `target_rule`), payload_digest, correlation `rid#idx`, max_uses, not_after_tick = commit tick + window. |
| Crash after commit | `extout.py` outbox rows in the world DB; `extsvc.py` `dispatch_pending` | intent + cap survive `crash()`/`restart()`; redelivery uses the SAME chain id. |

## Mutants (P1f-9), each at its real site
| Mutant | Site | Killed by |
|---|---|---|
| adapter_success_trusted | `extout.py` `dispatch` (OK reply -> state) | `test_adapter_success_trusted_false_reconciled_success` |
| credential_scope_broadened | `extout.py` `_caveats` (drops target + payload_digest, G4-E5) | `test_credential_scope_broadened_effect_outside_scope` |
| policy_gate_in_adapter | `service.py` `_txn` (rule skipped) + `extout.py` `_gate_hold` (rule re-implemented adapter-side) | `test_policy_gate_in_adapter_*` |
| idempotency_disabled | `extout.py` `_fresh_cap` / `_eligible` | `test_idempotency_disabled_duplicate_effect` |
| observation_coupled | `extrecon.py` `_adapter_snapshot` / `reconcile` | `test_observation_coupled_false_reconciled_success` |
| divergence_rewritten | `extrecon.py` `outcome_state(compare=False)` | `test_divergence_rewritten_misses_target_mutation` |

## Interpretations and open items (reported, not silently chosen)
1. Public `OUTCOME.evidence` is `[]`: G4-E6 (namespaced strings) contradicts the frozen `outcome.validate_outcome` / schema (positive ints). Internal records keep E6 form (`extrecon.public_evidence` is the single switch).
2. Dispatch is inline after the decision AND via `dispatch_pending` (resubmission / crash recovery); `submitted` counts only dispatch_pending submits.
3. A commit without request_id correlates as `anon-tx<N>` (the frozen text assumes a request_id).
4. P1f-6's order alone can yield a forbidden transition if a later snapshot shows FEWER rows (decreasing watermark); `next_state` then keeps the previous state.
