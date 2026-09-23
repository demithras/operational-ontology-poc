# Implementation notes

Running log of design decisions, ports, endpoints, deviations, and
next-phase handoff notes, one section per phase. Read this before starting
work on any phase.

## Phase 2 — Fake ERP/MES/WMS source systems

Tag `poc-v0.2-sources`. Spec: `docs/experiment/spec/02`, `03`, `04`, `06`,
`09`, `12`, `13`.

### Ports (154xx range, see `.env.example`)

| Service | Host port | Notes |
|---|---|---|
| Postgres 16 | 15432 | one server, 5 databases (see below), `wal_level=logical` set now for Phase 6 |
| ERP (FastAPI) | 15401 | |
| MES (FastAPI) | 15402 | |
| WMS (FastAPI) | 15403 | only service with idempotency + fault injection |

Databases (one role each, `CONNECT` revoked from every other role —
`db/init/00_init.sh`): `erp`, `mes`, `wms`, and two forward-looking ones
created now so no later phase needs a data-losing reset to add them:
`ontology_hot` (Phase 3+), `baseline` (Phase 8 A/B).

### Services

One shared root `Dockerfile` (python:3.12-slim + fastapi/uvicorn/
psycopg[binary,pool]); `docker-compose.yml` picks which service runs per
container via `command:`. Each service: raw SQL via psycopg3 (no ORM,
`services/<sys>/schema.sql` applied idempotently — `CREATE TABLE IF NOT
EXISTS` — at FastAPI `lifespan` startup), a `ConnectionPool`
(`services/common/db.py`), and only its own `SERVICE_DB_*` credentials —
never another system's.

**ERP** (`services/erp/`): `suppliers`, `parts` (id `PART-xxxxx`),
`purchase_orders` + `purchase_order_lines`. `GET /health`,
`GET|/{id} /suppliers`, `/parts`, `/purchase_orders`,
`POST /purchase_orders/{po_id}/delay {expected_at, reason}` (the
supplier-delay event; 404 unknown PO, 409 on a RECEIVED/CANCELLED
terminal PO).

**MES** (`services/mes/`): `production_lines`, `work_orders`,
`bom_requirements` (part id `COMP-xxx`). `GET /health`, `/production_lines`,
`/work_orders` (+ `?status=`), `POST /work_orders/{id}/reschedule
{new_planned_start}` (404 unknown, **409 on DONE/CANCELLED** — the
state-machine invariant from `03_domain_scenario.md`).

**WMS** (`services/wms/`): `warehouses`, `inventory_lots` (part id
`SKU-xxxxx`, `available` a Postgres `GENERATED ALWAYS AS (on_hand -
reserved) STORED` column, `CHECK (on_hand >= reserved)`), `transfers`.
`GET /health`, `/warehouses`, `/inventory_lots` (+ `?part=&warehouse_id=`),
`POST /transfers {action_execution_id, source, destination, part,
quantity}`, `GET /transfers/{id}`, `POST /transfers/{id}/reverse`. Test-mode
only (`OO_TEST_MODE=1`): `POST /_test/faults/arm`, `POST /_test/faults/reset`,
`GET /_test/faults`, `POST /_test/inventory/set` (exact upsert of one lot —
lets concurrency tests set up known preconditions without depending on
seeded data or test order).

### WMS concurrency design

Two *different* problems, two different Postgres mechanisms
(`services/wms/transfers.py`):

1. **Same `action_execution_id` from N concurrent callers → exactly one
   effect (F10/F11).** A plain `SELECT ... FOR UPDATE` cannot lock a row
   that doesn't exist yet, so the very first of N concurrent identical
   requests has nothing to serialize on. Fixed with a
   **transaction-scoped Postgres advisory lock**,
   `pg_advisory_xact_lock(hashtextextended(action_execution_id, 0))`,
   taken before the existing-row check. All N requests serialize on the
   same 64-bit key; the lock releases automatically on `COMMIT`/`ROLLBACK`,
   so it can never leak on a crash. First request through does the real
   work; every other one finds the now-committed row and dedupes (same
   body hash → replay; different body hash → 409).
2. **Two *different* `action_execution_id`s racing for the same
   inventory (the spec's stock=100 / two 80-unit-request race).** An
   ordinary `SELECT ... FOR UPDATE` on the (already-existing) source+
   destination `inventory_lots` rows, locked in `warehouse_id` order so
   opposite-direction concurrent transfers can never deadlock each other.
   First to acquire the lock wins; the loser's own row is still recorded,
   with `status='FAILED'`, `actual_quantity=0` — never silently dropped.

Idempotency replay is keyed on a `body_hash` (sha256 of
`{source, destination, part, quantity}`) stored per transfer row: same
key + same body → 200 with `"replayed": true`; same key + different body →
409.

### Fault injection (`OO_TEST_MODE=1` only)

`services/common/faults.py`: an in-memory, lock-guarded registry, armed via
`POST /_test/faults/arm {mode, scope: "next_n"|"action_execution_id", n?,
action_execution_id?, params?}`. Process-local by design — the fault-
injecting services run as a single uvicorn worker (no multi-process
fan-out), so no shared external store is needed.

All 6 modes from `06_decision_and_action_runtime.md` are implemented and
each is independently verified via `GET` afterward (never trusting the
initiating response alone), in `tests/integration/test_wms_faults.py`:

- `return_500_before_commit` — rolled back before any row exists; `GET
  /transfers/{id}` → 404, stock unchanged.
- `return_200_without_commit` — the row is built, then the whole
  transaction is rolled back; the *response* still carries the fabricated
  data (marked with a `note`), but `GET` → 404, stock unchanged. This is
  the literal "world diverges from what the caller was told" case.
- `partial_commit` — commits a caller-specified `actual_quantity` (e.g.
  50 of a 60 requested); row `status='PARTIAL'`.
- `delay_commit` — sleeps before `COMMIT`; eventually succeeds normally.
- `commit_then_timeout` — commits normally, *then* sleeps before returning
  the HTTP response, so a short-timeout caller sees a client-side timeout
  even though the effect already happened. A retry with the same key/body
  recovers via idempotent replay (F14) — this is the one fault mode that
  needs a second request to observe the recovery, not just a `GET`.
- `duplicate_response` — **a literal duplicated HTTP response can't be
  represented over one request/response pair**, so this mode commits
  normally and flags the response (`fault_note`); the test demonstrates the
  actual duplicate-delivery scenario (F10/F19) by re-POSTing the identical
  body itself and asserting it still dedupes to the one committed effect.
  Documented here as a deliberate, honest simplification rather than a
  transport-layer fake.

### Seeding (`make seed` = `seed/generators/generate.py` + new `seed/load.py`)

`seed/load.py` connects **directly** to each system's Postgres database
using that system's own role credentials (not through the REST APIs) —
this is test-data provisioning, not the ontology layer cheating with
cross-database SQL (that boundary is about Phase 3+, and is enforced by
each service's role only ever holding one DB's credentials regardless).
Loads the generated dataset, then the canonical incident fixture
(`seed/fixtures/canonical_incident.yaml`) with its exact ids (`WO-42`,
`WH-A`, `WH-B`, `PO-991`, `S-7`, `PART-00192`/`COMP-A17`/`SKU-88429`), then
writes `seed/out/identity_truth.json`.

Two design decisions worth flagging for later phases:

1. **ID collision, discovered not assumed** (`seed/identity.py`): the
   generator's 5-digit-zero-padded ERP part-id scheme (`PART-{i:05d}`,
   `i` in `0..499`) collides at `i=192` with the canonical fixture's own
   chosen ERP id for `PX-17` (`PART-00192`). No other system collides
   (MES/WMS formats differ). Policy: the canonical fixture wins; the one
   generated part (`PX-0192`) is silently-but-*documented*-ly dropped from
   **ERP only** (present in MES/WMS as normal) — recorded per-part in
   `identity_truth.json` with a `note` field, never papered over. **Phase 3's
   identity resolver should treat `identity_truth.json`'s `null` fields as
   the ground truth for "this part legitimately has no representation in
   this system," not a bug.**
2. **`inventory_lots` aggregation** (`seed/loaders/wms.py`): the generator
   produces 10,000 raw lot rows over only 2,000 possible `(part,
   warehouse)` pairs (500 parts × 4 warehouses) to hit the Phase-0 volume
   target — meaning many rows share a pair by construction. WMS's
   operational schema is one row per `(part, warehouse)` (`UNIQUE (part,
   warehouse_id)`, matching `reference_model.state.WorldState.inventory`'s
   keying and the canonical fixture's one-lot-per-warehouse shape). The
   loader **sums** `on_hand`/`reserved` per pair before inserting (both
   stay non-negative and `on_hand >= reserved` automatically, since that
   already holds per raw row) and marks the aggregate `QUARANTINE` if *any*
   contributing raw lot was. The generator's 10,000-row output still exists
   on disk (`seed/out/inventory_lots.json`) as a pre-aggregation batch view
   for future performance/volume testing — it just isn't what gets loaded
   into WMS's transactional table 1:1.

Two smaller fixture gaps filled with documented defaults (fixture doesn't
specify them): canonical supplier `S-7`'s attributes
(`ACTIVE`/10-day-lead-time/`HIGH` risk — flavor only, not load-bearing for
Phase 2), `WO-42`'s production line (`LINE-00`, always present regardless
of seed) and `planned_finish` (`planned_start + 200`), and canonical
warehouses' `capacity_class` (`MEDIUM` fallback — moot in practice since
`WH-A`/`WH-B` always already exist from the generated dataset).

### Determinism proof

`tests/integration/test_seed_determinism.py` performs its own two
`make reset && make seed` cycles (the one integration test allowed to
rebuild the stack mid-suite) and hashes `GET /inventory_lots` — sorted,
business fields only (`lot_id`/`part`/`warehouse_id`/`on_hand`/`reserved`/
`quality_status`; `updated_at`/`version` are legitimately wall-clock/audit
fields that must NOT be part of a "same business dataset" claim) — across
both runs.

### Deviations / honesty notes

- No deviation from the brief's endpoint/fault list. `duplicate_response`
  is implemented as documented above (can't literally duplicate one HTTP
  response; the fault flags the scenario and the test drives the actual
  duplicate itself).
- `/_test/inventory/set` is an addition beyond the brief's explicit
  endpoint list, needed to give the concurrency/idempotency/fault tests
  deterministic, order-independent preconditions instead of depending on
  the shared canonical/generated seed data (which `test_canonical_scenario.py`
  and `test_seed_determinism.py` both mutate). It only exists when
  `OO_TEST_MODE=1`, same as the fault endpoints.
- `make test-integration`/`make test` require the stack to already be up;
  `test` prints an explicit skip line (never a silent omission or a faked
  pass) if it isn't reachable.

### What Phase 3 (semantic core) needs from here

- Per-system local-id vocabularies are exactly as specified: ERP
  `PART-xxxxx`, MES `COMP-xxx`(`COMP-{i:05d}` for generated, `COMP-A17` for
  the canonical part), WMS `SKU-xxxxx`(`SKU-{100000+i}` generated,
  `SKU-88429` canonical). `seed/out/identity_truth.json` is the ground
  truth to test the identity resolver against, including the one
  intentional gap (`ERP: null` for `PX-0192`).
  `WH-A`/`WH-B`/`WO-42`/`PO-991`/`S-7` are used directly by MES/WMS/ERP
  respectively — only `Part` needed cross-system alignment in this domain
  (warehouses live only in WMS, work orders only in MES, POs/suppliers
  only in ERP).
- WMS's `inventory_lots` is the operational one-row-per-`(part,
  warehouse)` view; do not expect it to reconcile 1:1 against
  `seed/out/inventory_lots.json`'s raw 10,000 rows without applying the
  same aggregation.
- CDC/Debezium is not wired yet (`wal_level=logical` is set so no data-
  losing reset is needed to add it in Phase 6) — Phase 3 reads/writes go
  through the REST APIs or, for seeding, direct owned-credential SQL, not
  a change stream.
