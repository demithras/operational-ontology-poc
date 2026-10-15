# Protocol P1f - r3_shared additions for Gate 4 (H28), landed BEFORE any builder starts

DRAFT (g4-design 2026-10-09). Exact signatures + semantics. New modules: r3_shared/extworld.py (ExternalWorld service +
client), r3_shared/extcap.py (capability tokens), r3_shared/extobs.py (ObservationClient), r3_shared/extadapter.py
(adapter protocol + request/reply forms), r3_shared/outcome.py (vocabulary + forms ONLY, no outcome function),
spec/external/<domain>.systems.json (frozen system declarations), schemas/external-systems.schema.json.
Variants may import r3_shared.ext* and r3_shared.outcome; never r3_oracle or r3_harness.

## P1f-1 Deploy parameter and Deployment additions (variant.py)

    Variant.deploy(..., external: ExternalBinding | None = None) -> Deployment

    @dataclass(frozen=True)
    class ExternalBinding:
        systems: dict              # the frozen spec/external/<domain>.systems.json document in force (P1f-3)
        adapters: dict[str, ActionAdapter]   # system name -> harness-supplied adapter (honest or Byzantine)
        root_caps: dict[str, str]  # system name -> root capability token issued by ExternalWorld for this deployment
        observer: ObservationClient          # P1f-5, read-only, own key
        window: int                # frozen WINDOW in ticks (P1f-3 default 8)

external=None -> legacy in-transaction external_write path, unchanged (H23-H27). external given -> the variant MUST
NOT call WorldHandle.external_write at all; every ops-spec `external` effect goes through the adapter of its system
AFTER the world commit (outbox: the intent - request_id, effect_index, I, cap token - is durable in the world
transaction or HistoryStore before dispatch, so restart() can resubmit with the same cap).

New Deployment methods (mutating rules of PROT-H23 apply: thread-safe, arm_crash applies where noted):

    def dispatch_pending(self) -> CallResult
        """Submit every durable, not-yet-submitted intent (and every resubmission R28-8 allows). OK {"submitted": n}.
        The harness calls it after each request and after restart(); variants may also dispatch inline."""

    def reconcile(self, request_id: str, watermark: int) -> CallResult
        """Read the observer with `observer.read(watermark=watermark)` and update the outcome record(s) of request_id
        by the variant's own outcome function (PROT-H28 R28-5). OK {"outcomes": [OUTCOME...]} (P1f-6 form, sorted by
        effect_index); INVALID {"reason":"unknown_request"} if request_id never committed or has no external effect.
        Observer raises ObserverUnavailable -> OK with states per P1f-6 rule U (never an error status)."""

    def outcome(self, request_id: str) -> CallResult
        """Self-report of the current outcome records without reading the observer (harness cross-check ONLY;
        never ground truth). OK {"outcomes": [...]}; INVALID unknown_request."""

Reply-status vocabulary of call_tool/direct for a request with external effects (frozen): the decision status as
before (OK/DENIED/INVALID/UNAVAILABLE/UNKNOWN); an OK body carries "outcomes": [OUTCOME...] with state PENDING (or a
later state if the variant reconciled inline). An adapter reply NEVER changes the decision status (R28-1/R28-2).

## P1f-2 ExternalWorld service (separate OS process, like the H27 anchor; r3_shared/extworld.py)

    python -m r3_shared.extworld_server --dir <ext_dir> --systems <systems.json> --socket <path>
Owns <ext_dir>/external.db (SQLite WAL) and a random root key generated at start (never written to disk until
close(), like the H27 HMAC log key; revealed in close() output for the evaluator). The harness+variant process runs
under the sandbox profile that denies writes to <ext_dir> (same mechanism as G2 decision a). Tables:
    effects(seq PK, tick, system, operation, target, payload_json, payload_digest, cap_chain, correlation, adapter_id)
    audit(seq PK, tick, system, operation, target, payload_digest, cap_chain, correlation, adapter_id, outcome,
          reason)    -- one row per write ATTEMPT; outcome in {applied, refused}
    sysstate(system, key, props_json, version)  -- the external system's own state (WMS transfer records, ERP PO
          expectedAt, MES plannedStart) updated by the frozen per-system semantics of P1f-3
    obs_keys / issued(root caps per deployment)
Client API (r3_shared.extworld.ExternalClient, socket):
    issue_root(deployment_id: str, system: str) -> str          # harness only, at deploy
    advance(tick: int) -> None                                   # harness only (control socket): sets the server
                                                                 # tick from the shared LogicalClock; monotone
    write(cap: str, operation: str, target: str, payload: dict, adapter_id: str) -> WriteReceipt
        # verifies the cap chain + every caveat; applies or refuses; ALWAYS appends one audit row.
        # WriteReceipt(status: "applied"|"refused", reason: str, seq: int) - returned to the ADAPTER only.
    observer_key(deployment_id) -> str                          # harness only; handed to ObservationClient
    close() -> {"root_key_hex": ..., "head": {"effects": n, "audit": m}}
Refusal reasons (frozen, check order): bad_signature -> unknown_root -> system_mismatch -> operation_mismatch ->
target_mismatch -> payload_mismatch -> correlation_missing -> expired (tick > not_after_tick) -> uses_exhausted.
Rows carry the SERVER tick (set only by the harness through advance on a separate control socket that adapters are
never given), so an adapter cannot forge time to dodge `expired`. Delayed adapter writes (catalogue D*) are executed
by the harness scheduler at the scheduled tick through the same write() call.

## P1f-3 Frozen system declarations (spec/external/<domain>.systems.json)

    {"version": "r3-external-1", "domain": "manufacturing", "window": 8,
     "systems": {
       "WMS": {"observability": "full", "operations": {"transfer": {"idempotency": "at_most_once",
               "target_rule": "transfer:<part>@<source>-><destination>", "semantics": "wms_transfer"}}},
       "ERP": {"observability": "full", "operations": {"expedite": {"idempotency": "at_most_once",
               "target_rule": "po:<po_id>", "semantics": "erp_expedite"}}},
       "MES": {"observability": "effects_only", "operations": {"reschedule": {"idempotency": "idempotent_set",
               "target_rule": "wo:<work_order_id>", "semantics": "mes_set_planned_start"}}},
       "GEN-NULL": {"observability": "none", ...generated system, Q3}}}
Payload rule (I.payload): the ops-spec `external` effect's payload object evaluated on the decision's canonical
inputs; payload_digest = sha256 of canonical JSON (sorted keys, compact separators, r3_shared.serial form). Target =
target_rule with the payload fields substituted (deterministic string). The ops-spec `target` (transfer/expedite/
reschedule) is the operation name. `semantics` names a pure ExternalWorld state-update function (WMS: append a
transfer record, move lot quantities; ERP: expectedAt -= 1; MES: plannedStart := new_planned_start) - this replaces
the domain rule hard-coded today in paladin/worldbridge.py `_after` (it is external truth, not adapter logic).
Proposed MES = effects_only and one generated `none` system per domain (Q3); the project overlay (Q2) adds
REGISTRY (full, at_most_once, publish) and NOTIFY (effects_only, idempotent_set, notify).

## P1f-4 Capabilities (r3_shared/extcap.py; macaroon-style, no new dependency: hmac + hashlib)

    CAVEATS = ("system", "operation", "target", "payload_digest", "correlation", "max_uses", "not_after_tick")
    def attenuate(cap: str, **caveats) -> str      # new token = old caveat list + new caveats; sig' = HMAC(sig, c)
    def caveats_of(cap: str) -> list[tuple[str, Any]]   # readable by anyone (bearer token is not secret-sealed)
    def chain_id(cap: str) -> str                  # sha256 of the FIRST attenuation step below the root: identifies
                                                   # one per-effect cap and all its further narrowings
    verify(root_key, cap) is server-side only (extworld). Semantics: a caveat repeated in the chain must be satisfied
    for EVERY occurrence (narrowing only); max_uses counts applied writes per chain_id; correlation format
    "<request_id>#<effect_index>". A root cap has caveats system=<S>, deployment=<id> only.

## P1f-5 ObservationClient (r3_shared/extobs.py) and observation topology

    class ObservationClient:
        def __init__(self, ext_dir: str, observer_key: str, systems: dict, fault: ObserverFault | None = None)
        def read(self, watermark: int) -> ObsSnapshot
            # ObsSnapshot(watermark: int, effects: list[EffRow], audit: list[AudRow] (empty for effects_only),
            #             complete_through_tick: int)  rows with tick <= watermark only; 'none' systems omitted.
            # raises ObserverUnavailable when the injected fault says so.
SQLite mode=ro; the observer_key is checked against obs_keys (a read without a valid key raises). It is constructed
by the harness, never by the variant. ObserverFault (harness-only, frozen kinds): unavailable(at reconcile points
set), lagging(k ticks: complete_through_tick := watermark - k, rows above it withheld).
observation-independence.json (evidence, P1f-7) records per system: action path {adapter_id, cap root id, socket},
observation path {observer key id, db open mode, process}, and the computed check shared_trust_root (bool) =
any shared key/socket/process-owned object. Any true -> contract inconclusive_if.

## P1f-6 Outcome vocabulary and form (r3_shared/outcome.py: constants + validate_outcome only)

    STATES = ("PENDING", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED", "UNKNOWN")
    OUTCOME = {"request_id": str, "effect_index": int, "system": str, "state": STATES, "confidence": "full"|"low",
               "evidence": [ledger seq ints, sorted]}   # exactly these 6 keys
Outcome function (normative; oracle and each variant implement it; NOT shared code). Inputs: I, snapshot X (or U =
observer unavailable), previous state P, class C, observability O, cap expiry E. Let M = applied effect rows with
correlation == I.correlation; A = audit rows with that correlation (empty unless O == full). Evaluate in this order:
  N  O == none                                   -> UNKNOWN, confidence low (always; evidence []).
  U  observer unavailable                        -> P if P in {RECONCILED_SUCCESS, RECONCILED_FAILED, DIVERGED},
                                                    else UNKNOWN.
  D1 P == DIVERGED                               -> DIVERGED (absorbing).
  D2 any row r in M or any audit row in A with (operation, target, payload_digest) != I's -> DIVERGED.
  D3 C == at_most_once and |M| > 1               -> DIVERGED.
  S  |M| >= 1                                    -> RECONCILED_SUCCESS.
  F  |M| == 0 and X.complete_through_tick > E    -> RECONCILED_FAILED.
  W  otherwise                                   -> PENDING (observer lagging or window open).
Audit rows that MATCH I and were refused (uses_exhausted, expired) are benign: they appear in `evidence` but do not
change the state. confidence = low iff O in {none, effects_only}. evidence = seqs of M (and of A when O == full) used.
Allowed transitions follow from the order above (RECONCILED_* -> DIVERGED only; PENDING/UNKNOWN -> any).

## P1f-7 Action adapter protocol (r3_shared/extadapter.py)

    @dataclass(frozen=True)
    class ExternalRequest:     # what a variant hands an adapter; exactly these fields
        request_id: str; effect_index: int; system: str; operation: str; target: str
        payload: dict          # canonical JSON-able
        envelope_text: str     # H27 byte-exact provenance envelope of the decision ("" when no history/anchor)
        cap: str               # the per-effect attenuated cap (R28-13); never a root cap
    @dataclass(frozen=True)
    class AdapterReply:        # UNTRUSTED; a variant may use it only to decide whether to resubmit (R28-8)
        status: str            # "OK" | "FAILED" | "TIMEOUT" | anything else (treated as FAILED)
        body: dict             # arbitrary (Byzantine adapters put policy/authority-shaped keys here)
    class ActionAdapter(Protocol):
        adapter_id: str
        def submit(self, req: ExternalRequest) -> AdapterReply
`submit` may raise; a variant treats any exception as TIMEOUT. Honest adapter: one ExternalClient.write with the
request's fields and cap; reply OK iff receipt applied. Byzantine adapters: catalogue in ORACLE-AND-HARNESS-G4 s3,
primitive ids frozen here: H0 honest | L1 false_success | L2 false_failure | L3 timeout_after_apply |
T1 target_substitution | T2 payload_mutation | T3 target_plus_intended | R1 duplicate_delivery | R2 cap_replay_other_request |
O1 omission | O2 delay(k) | G1 policy_refusal_reply | G2 authority_artefact_reply | G3 cap_reuse_broadening_attempt.
The harness also wraps every adapter with a recorder (harness-side, outside the variant) that logs each
ExternalRequest received -> byzantine-adapter-corpus.json.

## P1f-8 Variant declarations (module constants, read by the harness like G3-E24(3))

    ADAPTER_MODULES: tuple[str, ...]     # dotted module paths of adapter-side code (PROT-H28 1.3)
    EXTERNAL_HISTORY_PREFIXES: tuple[str, ...]  # new HistoryStore prefixes (intents, outcome records) for the H27
                                                # tamper discovery (G3-E15 pattern)
Paladin today: paladin.worldbridge, paladin.engine.effects (adapter part), paladin.engine.outcome. Conventional today:
conventional.effects. Both will add modules; the declaration is part of the candidate and frozen with it.

## P1f-9 Mutant names (mutants.py) and tests landing with P1f

    KNOWN["H28"] = ["adapter_success_trusted", "credential_scope_broadened", "policy_gate_in_adapter",
                    "idempotency_disabled", "observation_coupled", "divergence_rewritten"]
Tests (basenames test_p1f_*.py; r3_shared only, fakes for variants):
- extcap: attenuation narrows only; every caveat enforced; tampered sig refused; chain_id stable under narrowing.
- extworld: every refusal reason in frozen order (one case per reason + one case failing two reasons -> the earlier
  reason); audit row on every attempt; server tick monotone; adapter cannot reach the control socket path (sandbox).
- extobs: mode=ro (a write raises); bad key raises; lagging/unavailable faults; effects_only hides audit.
- outcome: validate_outcome exact keys/vocabulary.
- ExternalWorld lifecycle: server refuses to start without --dir/--systems; the H28 runner refuses a non-dev id when
  the server is not running (G3-E31b lesson).
