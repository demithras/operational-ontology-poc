# H29 protections - conventional variant (safe continuity and deterministic recovery, PROT-H29 / PROTOCOL-P1g)

Paths relative to `round3/src/conventional/`. Architecture (EQUIVALENCE-G5 'conventional'): a lease-TTL authority cache (never
fail-static), one circuit breaker + bulkhead per dependency node driven by the frozen dependency graph read as data, a durable
anchor journal written in the SAME world transaction as the effects, the existing transactional outbox for external effects, and
`recovery_view()` as plain ordered SELECTs. Everything is inert when `deploy(authority_source=None, resume=False)` (H23-H28 legacy path).
Only P1g forms/clients (`faultplane`, `authsvc`, `recovery`) come from `r3_shared`; lease cache, breakers, journal and recovery are implemented here.

| Id | Where | Mechanism | Tests (tests/conventional/) |
|---|---|---|---|
| Seam (P1g-1) | `variant.py` `deploy`, `service.py` `__init__` (`_g5`, `resume`) | authority_source -> `G5State`; resume rebuilds from the durable authority lineage only (no seeding), absent -> `CanonicalStateLost`; damaged lineage keeps the E-7 refusal (F8) | `test_conv_g5_recovery.py` |
| R29-0 lease-backed | `g5svc.py` `_g5_auth`, `_g5_adopt` | fetch (renew) on every governed decision while AUTH is up; compose the leased version with the local delegation table, make it durable, record the `authority` mark; hold the lease only in memory | `test_conv_g5_lease.py` |
| R29-1 no stale commit | `g5svc.py` `_g5_auth`, `auth_claim`; `service.py` `_txn` | decide under a lease with granted <= t < lease_until; past it or without one -> UNAVAILABLE AUTH; commit mark / idempotency record bind the leased digest, never "last known good" | `test_conv_g5_lease.py`, mutants `fail_open_on_authority_outage`, `stale_cache_after_restart` |
| R29-3 no fail-open disclosure | `lowreads.py` `read`/`_low`, `g5svc.py` `_g5_pregate("read")` | every read/low channel needs AUTH (a valid lease) before the low view is built | `test_conv_g5_deps.py::test_read_*` |
| R29-4 anchor before ack, tamper | `g5svc.py` `_g5_anchor` (pre-flight), `provenance.py` `finalize` (UNKNOWN in_doubt), `g5journal.py` | pre-flight `head()` blocks with zero effects; a root lost after the commit answers UNKNOWN in_doubt; redelivery / first governed call after resume completes the journal row (append, or rebuild an already-anchored envelope); damaged HistoryStore records are never consumed (`histledger.py`) | `test_conv_g5_recovery.py`, `test_conv_g5_hostkill.py`, `test_conv_g5_progress.py`, mutant `anchor_skipped_when_unavailable` |
| R29-5 no false success / duplicates | `store.py` idempotency (effect transaction), `g5journal.py`, `extout.py` | request_id ledger and outbox rows are atomic with the effect; redelivery returns the original decision with zero new rows; one stored cap per effect (`chain_ids` 1) | `test_conv_g5_recovery.py`, `test_conv_g5_hostkill.py` |
| R29-6 explicit unavailability | `g5deps.py` `unavailable`, `g5svc.py` `_g5_blocked`, `variant.py` `_safe` | UNAVAILABLE {dependency_unavailable, dependency: first down node of deps(op)}; policy denial never names a dependency; a stray DependencyUnavailable is mapped, never `internal_error` | `test_conv_g5_deps.py`, mutant `dependency_failure_as_denial` |
| R29-7 no misclassification | `g5svc.py` `_g5_input_invalid`, `tools.py` | input errors decidable without AUTH stay INVALID with a frozen name (`unknown_operation`/`unknown_tool`/`schema_invalid`/`bad_args`); a bad token while blocked is UNAVAILABLE, not DENIED | `test_conv_g5_deps.py`, `test_conv_g5_progress.py` |
| R29-8 hard restart | `service.py` resume branch, `g5svc.py` `_g5_after_resume` | nothing survives in memory; the resumed service holds no lease, appends nothing, calls no dependency before the first API call after `recovery_view()` | `test_conv_g5_hostkill.py` (SIGKILL CP1/CP2/CP3/CP6/CP8), `test_conv_g5_recovery.py` |
| R29-9/10/11 recovery view | `g5svc.py` `recovery_view` | committed (world_log commit marks, by seq), intents (outbox JOIN outcome, by key), authority (held lease only, else null), approvals_open (sorted fingerprints); pure SELECTs | `test_conv_g5_recovery.py`, mutant `nondeterministic_recovery`, `outbox_dropped_on_restart` |
| R29-12 safe progress | `g5deps.py` `Guard`/`DepGraph`, `extout.py` `dispatch` | per-node breaker (cooldown 0 = every call after a failure is a half-open trial) and bulkhead; a fault blocks only ops whose graph entry names the node; an EXT outage is not a delivery attempt | `test_conv_g5_deps.py`, `test_conv_g5_progress.py`, mutant `global_halt_on_fault` |

## Mutants (P1g-10), each at its real site and killed by its own test (`test_conv_g5_mutants.py`, clean build green on the same scenario)
| Mutant | Site | Killing class |
|---|---|---|
| fail_open_on_authority_outage | `g5svc.py` `_g5_auth` (held lease used although expired) | stale_authority_commit / forbidden_effect |
| global_halt_on_fault | `g5svc.py` `_g5_blocked` (any tripped breaker blocks every request) | safe-progress (i)/(iii) |
| stale_cache_after_restart | `g5svc.py` `_g5_after_resume` + `_g5_auth` (durable version held as an unexpiring lease, fetch skipped) | stale_authority_after_restart / stale_authority_commit |
| nondeterministic_recovery | `g5svc.py` `_g5_after_resume` (in-doubt intents resolved by a per-process salted pick) | recovery_nondeterministic |
| dependency_failure_as_denial | `g5svc.py` `_g5_auth` (AUTH down -> DENIED not_authorized) | misclassified_dependency_failure |
| outbox_dropped_on_restart | `g5svc.py` `_g5_after_resume` (undelivered intents closed as RECONCILED_FAILED) | recovery_divergence (RC2) |
| anchor_skipped_when_unavailable | `g5svc.py` `_g5_anchor` (pre-flight skipped) + `provenance.py` `finalize` (OK returned on AnchorUnavailable) | unanchored_ack |

## Frozen-text gaps found while building (no choice made silently; see reports/g5-conventional-report.md)
G1 commit-mark `authority_version`: with local delegations the composed-document digest differs from the leased digest; this build
   binds the LEASED digest (A(t)) in `commit` marks and `authority_used`; the H27 envelope still binds the composed document.
G2 INVALID reasons while blocked: R29-7 names the frozen set, P1g-5 promises a reason-map for existing strings (file not frozen yet);
   this build emits the frozen names directly while blocked and keeps the legacy strings when healthy.
G3 `approvals_open`: "sha256 hex of the canonical approval fingerprint" is undefined; this build lists `store.fingerprint` (already a sha256
   of {subject, on_behalf_of, operation, inputs}), de-duplicated because the validator demands strict order.
G4 a committed-but-unanchored decision (CP2) is completed lazily (redelivery or the first governed call / dispatch_pending after resume);
   anonymous commits (no request_id) cannot be redelivered and stay unanchored until then (Q11 finding for the oracle to judge).
