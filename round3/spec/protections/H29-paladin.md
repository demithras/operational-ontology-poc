# H29 protections - Paladin variant (protection spec: spec/protections/PROT-H29.md; protocol: spec/gate5/PROTOCOL-P1g.md)

Mechanism in one paragraph. Governance, decisions and the commit pipeline are the unchanged H23-H28 Engine path. What H29 adds is an
EXPLICIT dependency/lease layer in front of it (`src/paladin/continuity.py`, `leasing.py`, `depgraph.py`), active only when
`deploy(authority_source=AuthorityBinding)` is given (`self._h29`); `authority_source=None` is the legacy path and is byte-for-byte the
G4 behaviour. Authority is a versioned object with a validity window: every governed decision fetches (renews) a lease from the
AuthorityService; the leased document is adopted with one `authority` mark (edges and revocations in force kept), the commit mark and
`authority_used` carry the SERVICE version (`Core.stamp()`), and while AUTH is down a decision runs only inside granted_tick <= t <
lease_until. What a request needs is read from the frozen dependency graph as DATA (`DepGraph`); a blocked request answers the frozen
vocabulary with zero effects. Everything that must survive a SIGKILL is already durable (world marks, request ledger, outbox); the
rebuild is a projection of those stores plus the tick (`recovery_view`), and nothing is trusted that the next AUTH answer has not re-verified.

| Requirement | Mechanism (src/paladin/) | Tests (tests/paladin/) |
|---|---|---|
| R29-0 lease-backed continuity | `leasing.LeaseGate.acquire` (fetch on every decision; held lease honoured inside the strict window); `continuity._probe` / `_adopt` | test_pal_g5_lease `r29_0` (renewal ledger, t=lease_until blocked) |
| R29-1 no stale commit | commit mark `authority_version` = leased service digest (`core_g2.stamp`); expiry refuses (UNAVAILABLE AUTH); a new version is adopted before the decision | test_pal_g5_lease `r29_1` x2 (stale-sensitive: old OK / new DENIED; outage after publish) |
| R29-2 containment | unchanged H23/H28 gates + caps (a compromised identity or Byzantine adapter gets nothing the decision plane did not grant) | existing H23/H28 suites (regression), test_pal_g5_more CP4/CP5 |
| R29-3 no fail-open disclosure | every low-channel read goes through the AUTH gate (`deployment._low`) | test_pal_g5_lease `r29_3` |
| R29-4 anchor before ack, tamper | a pre-flight anchor probe blocks before any world write; unconfirmed commit -> UNKNOWN in_doubt; a stored OK is replayed only if the anchor holds it (`core_g2.unacked`); tampered authority record -> fail closed (E-7) | test_pal_g5_lease `r29_6` (in_doubt x2), test_pal_g5_recovery `f8`, mutant `anchor_skipped` |
| R29-5 no false success | request ledger (R5) + `unacked`; intent durable BEFORE the world COMMIT (H29 only) and voided when the COMMIT never happened (`ledger.recover` -> `Outbox.drop`); caps bound applied rows | test_pal_g5_lease `r29_5`, test_pal_g5_recovery (CP1/CP2/CP3), test_pal_g5_more (CP4/CP5, outcome plane) |
| R29-6 explicit unavailability | `continuity.guarded` / `_blocked`: UNAVAILABLE {dependency_unavailable, dependency}; unanchored commit UNKNOWN {in_doubt}; B4 `CanonicalStateLost` | test_pal_g5_lease `r29_6` x4, test_pal_g5_recovery `b4` x2 |
| R29-7 no misclassification | blocked -> never OK/DENIED/UNKNOWN-other; input errors decidable without AUTH -> INVALID schema_invalid (authenticated callers only) | test_pal_g5_lease `denied_never_names`, mutant `dependency_failure_as_denial` |
| R29-8 hard restart | no harness repair API used; `deploy(resume=True)` rebuilds from the durable stores only; lease cache is memory-only | test_pal_g5_recovery (spawned hosts, SIGKILL at CP1/2/3/6/7/8, CP4/CP5 via wrapper) |
| R29-9 RC1 determinism | `recovery_view` is a pure projection (world commit marks, outbox, tick); resume does no dependency I/O | test_pal_g5_recovery `r29_9_r29_10` (two hosts, byte copies), `resume_is_restricted` |
| R29-10 RC1 admissibility | committed = the world's own marks; intents = last durable outcome record; authority = null until AUTH answers | same test; mutants `stale_cache_after_restart`, `nondeterministic_recovery` |
| R29-11 RC2 equality | same projection after heal + dispatch + reconcile + probe read; redelivery adds no world/ledger rows | test_pal_g5_recovery `r29_11` (predicted view built from the services' logs) |
| R29-12 safe progress | per-operation dependency awareness from the graph: only the failing node's operations block; EXT/OBS loss never blocks a decision | test_pal_g5_more `r29_12` x2, mutant `global_halt_on_fault` |

## Mutants (P1g-10), each at its real site and killed by its own class (tests/paladin/test_pal_g5_mutants.py, clean = 0 on the same subset)
| mutant | site | own class |
|---|---|---|
| fail_open_on_authority_outage | `leasing.LeaseGate.acquire` (held lease used past lease_until) | stale_authority_commit + forbidden_effect |
| global_halt_on_fault | `continuity._probe` (probes every node, any fault halts all) | safe progress < 0.95 |
| stale_cache_after_restart | `leasing.LeaseGate.__init__` + `continuity.h29_build` (durable cache believed after resume) | stale_authority_after_restart (+ stale commit) |
| nondeterministic_recovery | `core.Core.__init__` -> `ledger.recover(salt)` / `histledger.recover(salt)` (per-process salt picks the winning record) | recovery_nondeterministic + recovery_divergence |
| dependency_failure_as_denial | `continuity._blocked` | misclassified_dependency_failure |
| outbox_dropped_on_restart | `extdispatch.ExtPlane.drop_undispatched` (called from Core on restart) | recovery_divergence (RC1 + RC2) |
| anchor_skipped_when_unavailable | `core.Core.run` (ack kept after anchor failure) + `core_g2.guard_history` | unanchored_ack |

## Decisions taken where the frozen text is silent (each also listed in the build report)
- An invalid token while blocked answers UNAVAILABLE (never DENIED); INVALID schema_invalid is given only to an authenticated caller whose input
  is wrong. Unknown operations are not in the graph: they need no dependency and keep the legacy reply.
- The AuthorityService version stamps every commit (including after delegate/revoke edges): the document digest is the "version"; edges and
  revocations ride on top of the leased base layer and do not change it in H29 mode (`stamp()`).
- A decision committed in the world but never anchored (crash between COMMIT and anchor append) answers UNKNOWN in_doubt on every redelivery
  and its intent is never dispatched (no provable envelope); the observer then shows no effect and P1f-6 rule F gives RECONCILED_FAILED after E.
- No Engine patch is needed for Gate 5 (VENDORED.json unchanged).

## G5 fix1 (errata G5-E10..E15)
- E12: the decision of every H29 commit (kind, subject, on_behalf_of, operation, args, pre-commit evidence, authority document, edge path) is journaled in the
  HistoryStore under `led/pend/<request_id>` inside the commit transaction and dropped once its anchor entry exists. `ContinuityMixin.complete_anchors` rebuilds the
  decision from that record plus the world's own commit mark (world_seq, tick, tx rows) and appends the missing entry: on resume, on the first governed call after heal,
  in dispatch_pending and in reconcile. Before the heal a redelivery answers UNKNOWN in_doubt / UNAVAILABLE ANCHOR; after it, the original OK with zero new rows.
  Paladin requires a request_id on every mutating call (INVALID before any commit), so the "commit without request_id" case cannot arise on this variant.
- E11: approvals_open = sha256(canon_json({subject, on_behalf_of|null, operation, inputs})), stored beside the claim fingerprint (`cfp`).
- E13/E14: unchanged behaviour, now covered by tests; authenticated callers get an INPUT_INVALID_REASONS reason while blocked, unauthenticated callers
  UNAVAILABLE naming the down node (token precedes schema in the frozen check order; both admissible under R29-7).
- E10: committed[].authority_version is the leased digest (test_e10). E15: the recovery tests assert one deterministic outcome per crash point.
