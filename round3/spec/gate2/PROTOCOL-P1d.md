# Protocol P1d - r3_shared additions for Gate 2 (H24 + H27), landed BEFORE any builder starts

FROZEN 2026-10-07 (author decisions 2026-10-07 #2; rulings in spec/gate2/OPEN-QUESTIONS.md). One shared commit by the orchestrator/protocol agent, with tests, before dispatch.
Everything here is variant-neutral. Signatures are Python; semantics are normative. Nothing here is a global switch.

## P1d-1 world store: write log, commit tick, tags, writer allowlist (world.py)

New table, written ONLY by WorldHandle methods inside the same SQLite transaction as the write they describe:
```
CREATE TABLE world_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, tx INTEGER NOT NULL, tag TEXT, tick INTEGER NOT NULL,
  writer TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, data_json TEXT NOT NULL);
-- kind: create|update|delete|link|unlink|external|mark ; tx = id of the enclosing transaction (autocommit write = own tx)
```
- `WorldStore(path, clock: LogicalClock | None = None, writers: frozenset[str] | None = None)`. `handle(writer)` raises
  ValueError when `writers` is given and writer is not in it (carried audit item: per-adapter writer identities +
  allowlist; the allowlist is the auth spec's `service_accounts[*].world_writers` union, built by the harness).
- `WorldHandle.transaction(tag: str | None = None)` -> context manager whose `__enter__` returns a `Tx` with
  `tx.id: int`, `tx.tick: int` (clock.now() read right after BEGIN IMMEDIATE succeeded; 0 when no clock) and
  `tx.mark(kind: str, payload: dict) -> int` (appends a `mark` row, ref = kind, returns seq). Nested use raises.
- Every create/update/delete/link/unlink/external_write appends one row (data_json = the canonical change) with the
  current tx id/tag/tick; outside a transaction the write gets its own tx id and tag NULL.
- `WorldReader.log(after_seq: int = 0) -> list[dict]` and `snapshot()` gains `"log_head": max seq`.
- Mark kinds used by Gate 2: `commit` {request_id, kind, authority_version} (one per effect transaction, required),
  `authority` {op: delegate|revoke|set_authority, edge?|edge_id?|version} (required for every authority mutation).
- Meter rules (r3_oracle): a canonical/external change whose tx has no `commit` mark = `unattributed_write`
  (forbidden); a write row by a writer outside the allowlist = `writer_violation` (forbidden); direct SQL writes to
  canonical tables that bypass the log are detected by snapshot-vs-log replay (`unlogged_write`, forbidden).
- Backward compatible: H23 code that does not tag still works; the H23 meter ignores world_log.

## P1d-2 clock (clock.py)

No API change. Frozen reading rule: `tx.tick` (P1d-1) is the ONLY logical time of a commit. LogicalClock gets a
`threading.Lock` around advance()/now() (harness advances from another thread in expiry races). Variants never call
advance().

## P1d-3 authority spec v2 (authspec.py, schemas/authority-spec-v2.schema.json)

- `spec: "r3-authority-2"` = every v1 field unchanged + `max_delegation_depth: int (1..16)` + `capabilities: [edge]`
  + `revoked: [edge_id]`. Edge schema exactly PROT-H24 section 1 (`additionalProperties: false`).
- `validate_strict(spec, ops_spec=None)` dispatches on `spec`; for v2 it additionally enforces, raising ValueError:
  unique edge ids; parent exists and precedes child in the list; issuer of a non-root edge == parent.child; no cycle
  (PROT-H24 2.2); no static delegate on any edge; depth <= max; every revoked id exists; scope subset and expiry
  non-amplification for every non-root edge (PROT-H24 2.5, static part); ops in scopes exist in ops_spec when given.
  Both variants call it on deploy/set_authority (equivalence item #1/#2 from the H23 audit stays closed).
- New pure helpers (shared definitions, not enforcement): `scope_covers(scope, op, resources) -> bool`,
  `scope_subset(child, parent) -> bool`, `edge_path(spec, edge_id) -> list[dict]`. Variants MAY use them (shared
  low-level library); the oracle re-implements them independently in r3_oracle/authority_v2.py and a test compares
  both on generated cases (a disagreement fails the build, never silently passes).
- `authority_version()` for v2 = sha256 of canonical v2 document with `capabilities` in issuance order and `revoked`
  sorted. `Deployment.authority_state() -> dict` returns that document (variant self-report; used for replay
  cross-checks only, never as ground truth).

## P1d-4 Deployment additions (variant.py)

```
def delegate(self, token: str, edge: dict, request_id: str) -> CallResult      # PROT-H24 s2; OK body {"edge_id"}
def revoke(self, token: str, edge_id: str, request_id: str) -> CallResult      # PROT-H24 s5
def authority_used(self, request_id: str) -> CallResult
    # PROT-H24 R24-6: OK body {"authority_version", "world_seq", "tick", "path": [edge ids], "on_behalf_of"};
    # INVALID "unknown_request" if never committed.
def replay(self, decision_id: str) -> ReplayResult                            # PROT-H27 s6
def explain(self, decision_id: str) -> ReplayResult                           # PROT-H27 R27-7
```
`@dataclass(frozen=True) class ReplayResult: status: Literal["VERIFIED","TAMPERED","UNRESOLVED"]; reason: str;
envelope: dict | None; artifacts: dict[str, bytes]` (digest -> bytes, only when VERIFIED).
- delegate/revoke are mutating requests: thread-safe, arm_crash applies, request_id idempotent (PROT-H23 R5).
- `Variant.deploy(..., state_dir=None, history: HistoryStore | None = None, anchor: AnchorClient | None = None)`.
  When `history` is given (H27 runs) every durable variant record other than the world store (envelopes, receipts,
  artifacts, approvals, idempotency ledger, authority versions) lives in it; state_dir is then None. When `anchor` is
  None, H27 APIs return UNRESOLVED `no_anchor` (H24-only runs do not need it).
- Unimplemented methods raise NotImplementedError("not implemented yet - G2"); the harness labels that
  `unsupported` and the evaluator makes the variant INCONCLUSIVE, never SUPPORTED.

## P1d-5 HistoryStore and TamperView (new r3_shared/histstore.py)

```
class HistoryStore:            # one SQLite file; key -> bytes; ordered by key; thread-safe; WAL
    def __init__(self, path: str): ...
    def put(self, key: str, value: bytes) -> None   # overwrite allowed (it is a mutable store)
    def get(self, key: str) -> bytes | None
    def delete(self, key: str) -> None
    def keys(self, prefix: str = "") -> list[str]
class TamperView:              # harness-only attacker interface on the same file (separate connection)
    def __init__(self, path: str): ...
    keys(prefix), read(key), write(key, value), delete(key), rename(old, new)
    def log(self) -> list[dict]   # every tamper primitive applied, for tamper-mutation-results.json
```
Key layout is the variant's choice. No credit for obscurity: the harness finds artifacts and envelopes by CONTENT
(the oracle's expected canonical bytes and the frozen envelope form); a class attribute `HISTORY_LAYOUT: dict[str, str]`
(record kind -> key prefix) is used only for records without a frozen form (approvals, idempotency). A wrong or
incomplete declaration is a fairness defect for the equivalence audit.

## P1d-6 Anchor service (new r3_shared/anchor.py client + r3_shared/anchor_server.py process)

Server: `python -m r3_shared.anchor_server --dir <anchor_dir> --sock <path>`; separate OS process; key = os.urandom(32)
in memory. Log file `anchor.log`: one canonical JSON line per entry
`{"stream","seq","decision_id","root","prev_entry","i","mac"}` with `prev_entry` = sha256 of the previous line and mac =
HMAC-SHA256(key, canonical entry without mac). Client (the only thing variants import):
```
class AnchorClient:
    def __init__(self, sock_path: str): ...
    def append(self, stream: str, seq: int, decision_id: str, root: str) -> dict   # receipt; AnchorError on seq gap/dup
    def get(self, stream: str, seq: int) -> dict | None
    def lookup(self, stream: str, decision_id: str) -> dict | None                 # continuation (R27-5)
    def head(self, stream: str) -> dict | None
class AnchorError(Exception): ...
def start_anchor(anchor_dir, sock_path) -> AnchorProcess   # harness/runner only; .close() -> revealed key + final head
def verify_anchor_log(anchor_dir) -> dict                   # evaluator: chain + MACs + head; pure
```
Enforcement and audit: PROT-H27 section 4 E1-E5. Import scan addition: paladin/conventional must not import
`r3_shared.anchor_server` or `r3_shared.histstore.TamperView`.

## P1d-7 Mutant names (mutants.py)

```
KNOWN["H24"] = ["non_attenuating_delegation", "stale_authority_cache", "revoke_commit_reorder", "expiry_inclusive"]
KNOWN["H27"] = ["digest_omission", "fallback_to_current", "evidence_rebinding", "receipt_self_trust"]
```
(frozen with the protection specs; Q4/Q5 ruled yes.)

## P1d-8 Tests that land with P1d (r3_shared only, fakes for variants)

world_log rows per write + tag/tick + allowlist refusal; tx.tick stable while clock advances mid-transaction; v2
validate_strict accept/reject table (cycle, amplification, depth, static delegate, dangling revoke); HistoryStore
round-trip + TamperView log; anchor: separate pid, seq gap/dup refused, verify_anchor_log detects an edited line, a
deleted line and a forged MAC (known negatives), harness-process write to anchor dir -> PermissionError under the
runner's sandbox; mutants.validate accepts the new names. One test-file basename per tree (test_p1d_*.py).
