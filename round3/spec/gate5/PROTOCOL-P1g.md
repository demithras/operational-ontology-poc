# Protocol P1g - r3_shared additions for Gate 5 (H29), landed BEFORE any builder starts

DRAFT (g5-design 2026-10-12, HEAD d673a2c). Exact signatures + semantics. New modules: r3_shared/faultplane.py (crash
points + dependency errors), r3_shared/authsvc.py + authsvc_server.py (AuthorityService), r3_shared/recovery.py (forms
ONLY: reply vocabulary, recovery_view form + validator, canonical JSON re-export), r3_shared/host.py (variant host
process + DeploymentProxy). Amended: r3_shared/world.py (crash hook, no-op unless armed), r3_shared/anchor.py and
r3_shared/extworld*.py (server-side partition/outage control ops), r3_shared/variant.py (deploy params, G5 methods,
g5_call), r3_shared/mutants.py (KNOWN["H29"]). New frozen data: spec/gate5/dependency-graph.json,
spec/gate5/envelope-ops.json, schemas/dependency-graph.schema.json. Variants may import r3_shared.{faultplane,authsvc,
recovery}; never r3_oracle or r3_harness. Every amendment is a no-op for H23-H28 paths (regression: their suites +
byte-identical H28 smoke evidence on the P1g commit).

## P1g-1 Deploy parameters and Deployment additions (variant.py)

    Variant.deploy(..., authority_source: AuthorityBinding | None = None, resume: bool = False) -> Deployment

    @dataclass(frozen=True)
    class AuthorityBinding:
        client: AuthorityClient    # P1g-2, data plane only, bound to this deployment id
        lease: int                 # frozen LEASE (envelope-ops.json), informational
        graph: dict                # the frozen dependency-graph.json document (P1g-4)

authority_source=None -> legacy: auth_spec + set_authority, unchanged (H23-H28). Given -> auth_spec is the version-0
document the service also starts with (same bytes); the harness NEVER calls set_authority; the variant obtains every
authority/policy version through client.fetch() and decides each governed request under a version whose lease is valid
at the decision tick (P1g-2). It still records adoption in the world (PROT-H24 s4 `authority` mark + `commit` mark
authority_version) - those marks are the variant's CLAIM, checked against the service log, never used by the oracle as
truth.
resume=True -> the durable stores (world file, state_dir or HistoryStore) already hold a previous incarnation's state;
deploy must rebuild exactly as restart() would (no re-seeding, no re-initialisation of authority/approvals/intents) and
must not append to the anchor, fetch a lease, write ExternalWorld or read the observer before the first API call after
recovery_view() (P1g-7 restricted phase). Durable state absent or unreadable -> raise faultplane.CanonicalStateLost
(PROT-H29 s9 B4) - never start empty.

New Deployment methods (G5; missing -> NotImplementedError("not implemented yet - G5") via g5_call):

    def recovery_view(self) -> dict
        """Self-report of the rebuilt canonical state in the frozen form RECOVERY_VIEW (P1g-8). Pure: no dependency I/O,
        no mutation; harness/oracle cross-check ONLY, never ground truth."""

    def dependency_status(self) -> dict
        """Self-report {node: "UP"|"DOWN"|"UNKNOWN"} of the variant's current belief per node of deps it uses
        (descriptive, e.g. circuit-breaker state; never compared, recorded in fault-sequences.jsonl for attribution)."""

## P1g-2 AuthorityService (separate OS process, H27-anchor pattern; r3_shared/authsvc.py, authsvc_server.py)

    python -m r3_shared.authsvc_server --dir <auth_dir> --socket <path>     (control socket = <path>.ctl)
Owns <auth_dir>/authority.db (WAL while live, DELETE at close - G4-E13) and an HMAC key generated at start, revealed at
close() (H27 pattern); the harness+variant host runs under the sandbox profile denying writes to <auth_dir>.
Tables: versions(seq, digest, doc_json, requested_tick, effective_tick), leases(seq, deployment, digest, granted_tick,
lease_until, mac), faults(seq, deployment, kind, from_tick, to_tick, mode), refused(seq, tick, deployment, op, reason).
Data plane (variant):
    AuthorityClient(sock, deployment_id).fetch() -> Lease
        Lease(digest: str, doc: dict, granted_tick: int, lease_until: int, mac: str)   # mac = HMAC over the other fields
        raises faultplane.DependencyUnavailable("AUTH") when an outage/partition covers (deployment, server tick)
        (mode drop: nothing logged except a `refused` row; mode reply_lost: lease granted + logged, reply dropped).
Control plane (harness only): publish(doc) -> digest; advance(tick); outage(deployment, from, to, mode); log() ->
versions + leases + faults + refused; close() -> {"key_hex", "head"}.
Lease rule (normative; the oracle recomputes it from log()): fetch at server tick t returns the version in force V(t)
with lease_until = t + LEASE, EXCEPT while a publish is pending: a publish at tick p sets effective_tick
f = max(p, max lease_until over leases already granted for any older digest); fetch at t < f returns the old digest with
lease_until = min(t + LEASE, f); fetch at t >= f returns the new digest. In force A(t) = digest with the greatest
effective_tick <= t. A lease is valid for a decision at tick t iff granted_tick <= t < lease_until (strict upper bound).
Consequence: honouring leases is always safe; a decision at tick t under a digest != A(t) is stale (PROT-H29 R29-1).
Leases are durable claims a variant may persist and reuse after restart (still valid by the same rule).
Renew-on-decision (PROT-H29 R29-0): while AUTH is reachable a variant fetches (or renews) on every governed decision, so
its lease_until is always the rule's value at that tick; the oracle's lease window for SAFE classification assumes it.
Fetch is a local socket round trip (~0.1 ms class); cost is reported in the comparative p95.

## P1g-3 Fault plane (r3_shared/faultplane.py) and server-side fault controls

    class DependencyUnavailable(Exception):   node: str     # raised by shared clients; str(e) == node id
    class CanonicalStateLost(Exception)
    NODES = ("AUTH", "ANCHOR", "OBS")  + tuple(f"EXT:{s}" for s in systems)     # frozen per domain by dependency-graph
    CRASH_POINTS = ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP4_adapter_before_apply",
                    "CP5_adapter_after_apply", "CP6_idle", "CP7_reconcile_after_read", "CP8_during_recovery")
    def arm(point: str, key: str) -> None          # host-only (set by the host on harness RPC); one armed point at a time
    def crashpoint(point: str, key: str) -> None   # no-op unless (point, key) is armed; then os.kill(os.getpid(), SIGKILL)
Hook sites (shared code; variants cannot route around them because these are the only write paths they are given):
- CP1/CP2: WorldHandle.transaction - immediately before / after COMMIT of a transaction containing a `commit` mark with
  payload request_id == key (P1d mark form; both variants write it today).
- CP3: AnchorClient.append - after the server acknowledged the append, before returning (key = decision_id).
- CP4/CP5: the harness adapter wrapper (frozen in r3_harness/h29/adapters_h29.py, wrapping the frozen H28 catalogue) -
  before / after ExternalClient.write of correlation == key.
- CP6: host RPC loop between two calls. CP7: ObservationClient.read return path (key = request_id of the reconcile call,
  set by the host before dispatching reconcile). CP8: the first dispatch_pending after resume (host RPC loop).
Server-side controls (control sockets only; adapters and variants never hold them - G4-E11):
- AnchorServer: partition(deployment_stream, from_tick, to_tick, mode in {drop, reply_lost}); appends during drop are
  refused (client raises DependencyUnavailable("ANCHOR")); reply_lost applies the append, logs it, then closes the
  connection (client raises DependencyUnavailable("ANCHOR")); reads (get/lookup/head) follow the same windows.
- ExternalWorld: outage(system, deployment, from, to) -> write raises ExternalUnavailable at the client (no effect row; an
  audit row with outcome `refused`, reason `unavailable` APPENDED AFTER the frozen P1f-2 reasons - check order:
  unavailable is evaluated first, before bad_signature, because a down system authenticates nothing; recorded in
  envelope-ops.json); partition(...) same with mode reply_lost (write applied, client sees ExternalUnavailable).
- AuthorityService: outage/partition as P1g-2.
- OBS: the existing P1f-5 ObserverFault (unavailable / lagging), unchanged and frozen in FREEZE_G4.
Every service writes its own fault log (activations, refused calls per deployment and tick); these server logs are the
independent record for Phi(t) and for the injection-effectiveness check (ORACLE-AND-HARNESS-G5 s7 invalid_if).

## P1g-4 Dependency graph (spec/gate5/dependency-graph.json; schema schemas/dependency-graph.schema.json)

    {"version": "r3-depgraph-1",
     "nodes": ["AUTH", "ANCHOR", "OBS", "EXT:*"],
     "surfaces": {"governed_mutation": {"decision": ["AUTH", "ANCHOR"]}, "read": {"decision": ["AUTH"]},
                  "replay": {"decision": ["ANCHOR"]}, "explain": {"decision": ["ANCHOR"]},
                  "reconcile": {"outcome": ["OBS"]}},
     "operations": {"manufacturing": {"transfer_inventory": {"surface": "governed_mutation", "outcome": ["EXT:WMS", "OBS"]},
                                      "expedite_purchase_order": {"surface": "governed_mutation", "outcome": ["EXT:ERP", "OBS"]},
                                      "reschedule_work_order": {"surface": "governed_mutation", "outcome": ["EXT:MES", "OBS"]}},
                    "project": {"<every op of spec/ops/project.json>": {"surface": "governed_mutation", "outcome": []},
                                "publish_result": {"surface": "governed_mutation", "outcome": ["EXT:REGISTRY", "OBS"]},
                                "notify_reviewer": {"surface": "governed_mutation", "outcome": ["EXT:NOTIFY", "OBS"]}},
                    "*": {"approve": {"surface": "governed_mutation"}, "delegate": {"surface": "governed_mutation"},
                          "revoke": {"surface": "governed_mutation"}}}}
Generated by a deterministic script from the frozen ops specs + systems.json (scripts/gen_depgraph.py); a test asserts
the committed file equals the script output and that every ops-spec operation of both domains (+ H28 overlay) appears
exactly once (set difference, not count). GEN-NULL (`record`) is EXT:GEN-NULL with no OBS (observability none).

## P1g-5 Reply vocabulary for unavailability (r3_shared/recovery.py constants + validate_reply)

    DEP_UNAVAILABLE = "dependency_unavailable"   # UNAVAILABLE body {"reason": DEP_UNAVAILABLE, "dependency": <node id>}
    IN_DOUBT = "in_doubt"                        # UNKNOWN body {"reason": IN_DOUBT}
    CRASHED = "crashed"                          # existing (UNKNOWN on the crashing call / UNAVAILABLE after, legacy only)
    STATE_LOST = "state_lost"                    # UNAVAILABLE, catastrophic boundary B4
    INPUT_INVALID_REASONS = ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args")
    def validate_reply(status: str, body: dict) -> None   # exact keys for the H29 forms above; raises ValueError
DENIED bodies must not contain the key `dependency` nor a reason in (DEP_UNAVAILABLE, IN_DOUBT, CRASHED, STATE_LOST).
Note: the existing INVALID reason strings of each variant are mapped to INPUT_INVALID_REASONS by a frozen table in
spec/gate5/reason-map.json built from the H23 oracle's reason classes (OPEN-QUESTIONS Q9) - no free-text matching.

## P1g-6 Variant host process (r3_shared/host.py) - hard crash and resume

    python -m r3_shared.host --variant <name> --mutants <csv> --ctl <fd>   (always multiprocessing "spawn"; fresh
    interpreter per incarnation; no fork; no import-time temp dirs - G4 lesson)
    class DeploymentProxy:   # harness side; same method names as Deployment + arm(point, key), advance(tick), pid
        def __getattr__(self, method) -> Callable    # JSON-over-pipe RPC; a dead host raises HostDead
The host builds clocks/clients from paths in the deploy message (world file, state_dir/history file, anchor socket,
authority socket, ext data socket, observer key, adapters by catalogue id + seed). Crash = SIGKILL at an armed point
(P1g-3); the harness sees HostDead (the in-flight call's reply is recorded as `no_reply`). Resume = new host with
resume=True on the same paths. The host's shared LogicalClock is driven only by harness advance() RPCs, and the
harness advances the anchor/authority/ExternalWorld server ticks in the same step (one absolute clock - G4-E26).

## P1g-7 Recovery checkpoints (normative schedule)

RC1 (after every resume): the harness copies the durable stores while no host runs (kill is complete), then resumes TWO
hosts A and B (A on the original paths, B on the copy) at the same absolute tick with the RESTRICTED dependency state:
AUTH, EXT:*, OBS unavailable (server-side outage for both deployment ids), ANCHOR read-only (appends refused); calls
recovery_view() on both; compares byte-exactly (R29-9); B is then terminated and its copy deleted. A continues.
(The restricted phase is itself in-envelope: a restart while dependencies are down.)
RC2 (end of each recovery event): lift every fault; dispatch_pending(); advance to max(E)+2 over open intents;
reconcile(request_id, watermark=now) for every request with external effects; one read() that needs AUTH; then
recovery_view() (R29-11) and redelivery of every committed request_id (behavioural equality).

## P1g-8 RECOVERY_VIEW form (r3_shared/recovery.py: RECOVERY_VIEW_KEYS, validate_recovery_view, canon_json re-export)

    {"form": "r3-recovery-1",
     "committed": [{"request_id": str|null, "world_seq": int, "authority_version": hex}]   # sorted by world_seq
     "intents": [{"request_id": str, "effect_index": int, "system": str, "chain_ids": int,  # distinct cap chains minted
                  "state": STATES (P1f-6), "confidence": "full"|"low"}],                   # sorted (request_id, effect_index)
     "authority": {"version": hex|null, "lease_until": int|null},
     "approvals_open": [sha256 hex of the canonical approval fingerprint]}                  # sorted, unconsumed only
Exactly these keys; canonical JSON = r3_shared.extadapter.canon_json (G4-E1). Equality = byte equality of canon_json.
`committed` lists governed decisions with an OK commit mark (anonymous commits: request_id null, G4-E17 correlation
form unchanged). `chain_ids` is compared (R28-8: one chain per effect -> 1; idempotency_disabled-like recovery -> > 1).

## P1g-9 G5 harness entries (variant.py)

    G5_METHODS = ("recovery_view", "dependency_status")
    def g5_call(deployment, method, *args, **kwargs)     # NotImplementedError("not implemented yet - G5") when missing
    def g5_deploy(variant, *args, authority_source, resume=False, **kwargs)   # NotImplementedError when deploy lacks them

## P1g-10 Mutant names (mutants.py) and tests landing with P1g

    KNOWN["H29"] = ["fail_open_on_authority_outage", "global_halt_on_fault", "stale_cache_after_restart",
                    "nondeterministic_recovery", "dependency_failure_as_denial", "outbox_dropped_on_restart",
                    "anchor_skipped_when_unavailable"]
Tests (basenames test_p1g_*.py; r3_shared only, fakes for variants):
- authsvc: lease rule on a scripted publish/fetch log incl. pending publish, boundary ticks (lease_until strict), mac
  verification, outage/partition modes, sandbox denies writes to <auth_dir>, close() reveals the key; refuses to start
  without --dir.
- faultplane: each crash point fires exactly once when armed and never when unarmed (H23-H28 suites unchanged); CP1
  leaves no committed row, CP2 leaves the committed row (SQLite durability), both observed from a WorldReader in the
  parent; SIGKILL leaves no zombie (host reaped).
- anchor/extworld fault controls: drop vs reply_lost semantics; refused rows logged server-side; `unavailable` audit
  reason order.
- host: spawn only (assert start method), two hosts resumed from byte copies of a FakeVariant store give identical views;
  a FakeVariant with a module-level cache that survives a cooperative crash() does NOT survive a host kill.
- recovery: validate_recovery_view exact keys/order; validate_reply forms; DENIED with `dependency` rejected.
- dependency graph: generated file == committed file; every op of both domains present once.
- lifecycle: run_h29.py refuses a non-dev id when the anchor, ExternalWorld or AuthorityService socket is not reachable
  (G3-E31b) - all three, one refusal test each.
