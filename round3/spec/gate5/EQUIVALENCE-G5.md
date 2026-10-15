# Gate 5 equivalence (H29): Paladin mechanism vs strongest conventional equivalent

DRAFT (g5-design 2026-10-12, HEAD d673a2c). DUAL_TRACK: same seams (AuthorityBinding, host process, fault plane,
ExternalBinding, anchor), same services and trust class (AuthorityService, anchor, ExternalWorld, observer), same corpus,
oracle and evaluator. Shared code is limited to P1g (forms, vocabulary, services, clients, host, crash hooks) and P1f.
Each variant implements its own lease cache, dependency tracking (circuit breaker), outbox recovery, idempotency,
rebuild and recovery_view. Conventional builder receives PROT-H29 + P1g only, never Paladin source.

## What exists today (read at d673a2c) - starting points, not credit

| area | Paladin today | Conventional today |
|---|---|---|
| durable state | with history: every durable record in HistoryStore (HistLedger), else state_dir/ledger.sqlite (in-memory request ledger risk noted in the H23 audit; self-declared gap "death between durable write and world COMMIT unrecoverable", G2) | ALL durable state (effects, idempotency ledger, approvals, authority) in the world DB in the SAME transaction as the effect - atomic by construction; with history, histledger.py |
| crash/restart | cooperative `_die` drops Core; restart rebuilds Core from durable stores (`_build(restart=True)`) | cooperative `crash()` clears memory; `restart()` reloads authority from the store; damaged lineage -> stays up refusing mutations (E-7) |
| authority | pushed by set_authority, recorded as world `authority` mark | same (authority_ops.py) |
| outbox/recovery (H28) | extoutbox/extdispatch/extoutcome; after crash never re-calls adapter (UNKNOWN until observer decides) | extout/extrecon/extsvc; outbox redelivery with the same cap |
| dependency failure reply | free-text UNAVAILABLE reasons; anchor failure behaviour per H27 (deploy raised on tampered store at G2 dev1) | free-text; lock timeouts classified (P11) |

## Per protection

| PROT-H29 item | Paladin mechanism (expected) | Strongest conventional equivalent | Fairness risk / audit point |
|---|---|---|---|
| R29-0/R29-1 lease-backed authority, no stale commit | Capability graph compiled from the leased authority version; version pinned in the decision (IR authority version binding), lease_until checked in the gate pipeline | PDP with a versioned policy cache with TTL = lease (OPA bundle / RBAC-informer style), version bound in the decision record; cache keyed by lease, never by "last known good" | Neither may use "last known good" past lease_until; the conventional default in industry IS fail-static - DUAL_TRACK requires the strongest SAFE equivalent, so the builder brief says lease-bounded explicitly |
| R29-3 no fail-open disclosure | sovview over the leased version; AUTH down past lease -> UNAVAILABLE | lowview over the leased version; same | same oracle (H26 lowproj) for both |
| R29-4 anchor before ack, tamper not trusted | provenance envelope anchored before reply; replay detects tamper (H27) | append-only content-addressed audit + anchor before ack; histledger verification on resume | both must answer UNAVAILABLE ANCHOR (drop) or UNKNOWN in_doubt (reply_lost after commit) - deferred anchoring with OK ack is the anchor_skipped mutant for BOTH |
| R29-5 no false success / duplicates | durable idempotent execution (Engine journal), caps per effect (H28) | idempotency key table in the effect transaction (already atomic), outbox with stored per-effect token | Paladin's in-memory request-ledger gap (H23 audit) is the most likely H29 finding; measured, not pre-fixed by the designer |
| R29-6/R29-7 explicit unavailability | Engine knows each gate's dependency (authority, anchor, adapter, observer) -> dependency id in the refusal | per-dependency circuit breakers (closed/open/half-open) + typed DependencyUnavailable exceptions mapped to 503-style replies naming the dependency | both read node ids from dependency-graph.json (data); per-domain dependency code = static hit (C29-7) |
| R29-8..R29-11 deterministic recovery | deterministic projection/replay from journal + world log; recovery_view = projection | write-ahead/outbox tables replayed in primary-key order; recovery_view = SELECTs ordered by key | determinism must not come from harness ordering: RC1 A/B uses byte copies and fresh spawned processes for both |
| R29-12 safe progress | per-operation dependency awareness from IR (only the failing capability's ops blocked) | bulkheads: per-dependency breaker scoped to ops whose graph entry names it; unrelated ops proceed | a conventional "global maintenance mode" on any breaker would fail (i)-(iii) exactly like global_halt_on_fault - fair symmetric test |
| s9 boundary | deploy(resume) raises CanonicalStateLost when stores missing | startup check (schema + lineage) refuses to start empty when a deployment id was seen before | must be keyed on durable evidence (anchor stream head > 0 for this deployment) - both may consult the anchor read-only at resume (P1g-7 allows ANCHOR reads) |

## Fairness risks to rule on before freeze

E1 Conventional starts closer to the target: atomic same-transaction durable state means fewer recovery paths. This is
   a genuine conventional property, not an unfair advantage; Paladin may adopt the same pattern (no restriction).
E2 Lease-backed continuity (R29-0) is new code for both; it must be implemented independently (not shared) - recommended
   like the H28 outcome function (G4 Q4): only the service, client and lease RULE text are shared.
E3 Paladin's H28 recovery style (never resubmit after crash) vs conventional redelivery: both remain legal (R28-8).
   RC2 compares only ledger-determined fields (states via P1f-6 from the actual ledger, chain count), so either style
   yields an exact oracle prediction; outcome_progress_loss is computed on no-crash honest intents only (G4 Q11 pattern).
E4 Host process overhead (spawn per incarnation) is identical; Paladin's slower startup (IR boot) inflates its wall time,
   descriptive only (p95 from host RPC round trip).
E5 dependency_status() is descriptive; neither variant gains or loses from what it self-reports.
E6 HARDENING_LEDGER.jsonl gets one row per R29 item per variant before dev1; the equivalence auditor checks rows and
   looks for an obvious missing conventional control (e.g. no breaker, global lock on outage) before measurement.
