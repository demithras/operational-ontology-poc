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

## Phase 3 — Semantic core + CDC ingestion

Tag `poc-v0.3-semantic`. Spec: `docs/experiment/spec/00`, `04`, `05`, `07`,
`08`, `09`, `14`. ADR: `docs/adr/0002-cdc-now-not-deferred.md` — Debezium
CDC ingestion is built in Phase 3 (not deferred to Phase 6 as the plan
table implied) because it is the *only* path by which observed source
facts enter the semantic core, and Phase 6 reconciliation reuses this
exact pipeline rather than building a second one.

### Ports (154xx range, see `.env.example`)

| Service | Host port | Notes |
|---|---|---|
| RDF4J server+workbench | 15480 | REST API at `/rdf4j-server`, workbench UI at `/rdf4j-workbench`; repository id `oo` |
| Kafka (KRaft, external listener) | 15492 | see "Kafka dual-listener" below; internal compose traffic uses `kafka:9092` |
| Debezium Connect REST API | 15483 | connector CRUD, `/connectors/{name}/status` |
| `services/ingestion` health | 15484 | `GET /health` — JSON counters, F38 visibility |

### docker-compose additions

`kafka` (`quay.io/debezium/kafka:2.7`, single-node KRaft `NODE_ROLE=combined`
via `docker-entrypoint.sh` env-var wrapper — simpler than the raw
`apache/kafka` image and vendor-matched to `connect`), `connect`
(`quay.io/debezium/connect:2.7`, bundles the Postgres connector plugin —
no custom image needed), `rdf4j` (`eclipse/rdf4j-workbench:6.1.0-tomcat` —
pinned; Docker Hub's newest tag turned out to be RDF4J **6.1.0**, not an
older version, which matters for the repository-config Turtle vocabulary
below), and `ingestion` (shared root `Dockerfile`, `command: python3 -m
services.ingestion.consumer`, same one-Dockerfile-many-commands pattern as
erp/mes/wms).

**Kafka dual-listener** (found empirically): a single `PLAINTEXT://kafka:9092`
listener bound to the "kafka" hostname's own resolved address works fine
for other containers but breaks host-side clients — a host process can
bootstrap via the published port, then fails on its first real fetch with
`Failed to resolve 'kafka:9092'`, because Kafka clients reconnect to
whatever the broker's *metadata response* advertises, not just the
bootstrap address. Fixed with two listeners: `PLAINTEXT://kafka:9092`
(compose-internal) and `EXTERNAL://localhost:$KAFKA_HOST_PORT`
(host-side), `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP` mapping both to
`PLAINTEXT`, `CONTROLLER` listener moved to its own port 9094 —
**`KAFKA_CONTROLLER_QUORUM_VOTERS` must reference that same port**; moving
`CONTROLLER` without updating the voters string breaks KRaft controller
registration and the broker exits with "unable to register with the
controller quorum" (hit once during implementation, fixed).

**RDF4J healthcheck**: `eclipse/rdf4j-workbench`'s Tomcat/JRE base image
has neither `curl` nor `wget` nor `python3` — only `bash` — so the
healthcheck speaks raw HTTP/1.0 over `bash`'s `/dev/tcp` (see
`docker-compose.yml`'s `rdf4j` service comment for the exact one-liner,
verified against the running container).

### RDF4J repository (`contracts/rdf4j/v1/oo-repository-config.ttl`)

A `ShaclSail` wrapping an `openrdf:NativeStore`. Config vocabulary
**verified empirically** against the running RDF4J 6.1.0 container (this
version uses the *current* `tag:rdf4j.org,2023:config/` config namespace,
not the legacy `openrdf.org` one some older examples online still show):
the PUT body's subject must be a bare `[]` blank node — `<#oo>` 500s with
"Not a valid (absolute) IRI" because the PUT has no base IRI to resolve a
relative IRI against.

Bootstrap: `services/ingestion/bootstrap_rdf4j.py` (run by `make up`,
idempotent — skip-if-exists for the repository, clear-then-reload every
time for the ontology and SHACL shapes graphs). **Empirically discovered
oddity**: triples POSTed into RDF4J's reserved SHACL shapes graph
(`http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`) are consumed into
`ShaclSail`'s own internal shapes model and are **not** retained as
ordinary queryable graph data — a `GRAPH <...> {}` SPARQL query or
`/size?context=...` against that graph correctly reports **0** even when
the shapes are fully active. `bootstrap_rdf4j.py` therefore verifies
success with a functional probe (POST an incomplete `oo:Decision`, assert
HTTP 409) instead of a triple count.

**Verified transactional rejection** (phase3.md item 2's core claim): a
negative fixture POSTed to `/repositories/oo/statements` returns **HTTP
409** with a full SHACL `ValidationReport` body, and a follow-up `ASK`
query confirms nothing was committed. Every negative fixture is proven
this way in `tests/contracts/test_shacl_rdf4j_transactional.py`, live
against the real repository — not just via pyshacl in-process.

### Ontology (`contracts/ontology/v1/`)

Three files: `oo-core.ttl` (Decision/EvidenceSnapshot/DecisionActivity/
ActionExecution/Outcome/HumanActor/SoftwareAgent as PROV-O specializations;
`oo:DecisionStatusScheme` as a SKOS concept scheme — deliberately has no
concept notated bare `"SUCCESS"`, so `sh:in` rejects it by construction,
not by a separate rule), `oo-observation.ttl` (`oo:FactKindScheme`
Observed/Inferred/Derived/Asserted; `oo:Observation` — one per applied CDC
event; `oo:SourcePosition` — latest LSN/version per (source, table, pk),
for Phase 5 evidence snapshots to cite; `oo:IdentityMapping` /
`oo:QuarantinedIdentity`), `fac-core.ttl` (Supplier, Part, PurchaseOrder,
PurchaseOrderLine, InventoryLot, Warehouse, WorkOrder, BomRequirement,
ProductionLine, Shipment; `fac:availableQuantity` per the 07 V1 baseline,
computed as `on_hand - reserved` by `services/ingestion/mapping.py` rather
than trusted from WMS's generated column, since generated-column inclusion
in the logical-replication row image is a Postgres-version-dependent
detail not worth depending on).

`fac:Shipment` is declared (required by phase3.md item 3's class list) but
deliberately **unpopulated** — WMS's `transfers` table models
inter-warehouse transfers, not outbound customer shipments, and no Phase 2
source produces shipment rows.

Named graphs (`services/common/rdf_graphs.py`): `.../graph/ontology`
(the files above), `.../graph/observed` (current entity state, one upsert
per entity), `.../graph/provenance` (`oo:Observation` / `oo:SourcePosition`
/ `oo:IdentityMapping` / `oo:QuarantinedIdentity`). `oo:factKind` is also
asserted per-observation as a belt-and-suspenders (05_ontology_and_contracts.md
"Evidence must distinguish observed/inferred/derived/asserted").

### SHACL (`contracts/shapes/v1/`)

`decision-shape.ttl` (all 12 exactly-1 properties from 05's Decision
object list; `oo:evidenceSnapshot` additionally `sh:class
oo:EvidenceSnapshot` — a *referenced* snapshot must actually be typed as
one, not merely present as a property value); `action-execution-shape.ttl`
(`oo:quantity` `sh:minInclusive 1`; `oo:sourceWarehouse` `sh:disjoint
oo:destinationWarehouse` for source != destination); `fac-core-shape.ttl`
(datatype/cardinality only for `fac:InventoryLot`/`fac:Part`).

**Deviation, found empirically**: `fac-core-shape.ttl` originally also had
`sh:class fac:Part` / `sh:class fac:Warehouse` on `fac:InventoryLot`'s
reference properties (referential integrity). This broke on the very
first real CDC-sourced write — SHACL validates the *whole* repository
dataset, and CDC delivers each source table's rows independently and out
of any cross-table order (F20/F35 already require ingestion not to assume
ordering), so an `InventoryLot` event can legitimately arrive before its
`Warehouse`/`Part` has ever been observed. Removed; this is exactly the
SHACL misuse `docs/experiment/spec/14_risks_and_open_questions.md` R3
warns against ("some business rules are better represented in policy code
than graph constraints") — referential integrity across independently-
arriving CDC streams belongs in a later policy/reconciliation layer, not a
transactional graph constraint.

Fixtures: `tests/contracts/shacl/{positive,negative}/*.ttl`, one file per
case, covering 08_test_strategy.md's exact negative list (missing actor /
evidence / policy version, negative quantity, malformed transition) plus
phase3.md's own two ActionExecution rules. Verified with a known-negative
methodology, not just a clean run: every negative fixture is asserted to
NOT conform (both via pyshacl and via the live RDF4J 409).

### Identity resolution (`services/identity_resolver/`,
`contracts/identity/v1/mapping_rules.yaml`)

Two rule kinds, tried in priority order: `explicit_override` (hand-authored
source-id -> canonical-id table; always wins over the pattern rule for the
same source id) and `pattern` (regex + integer offset per system, no
eval/exec). Verified against **all 501 entries** of
`seed/out/identity_truth.json`, including the documented ERP-id collision
(`PART-00192` resolves only to the canonical fixture's `PX-17`, never to
the generated `PX-0192` — `generated-index-v1` never gets a chance to
claim it because the explicit-override check runs first). Unrecognized
source ids quarantine as `oo:QuarantinedIdentity` with reason
`unrecognized_source_identifier_format` — never guessed (F09).

**Bug caught empirically**: `mapping_rules.yaml`'s system keys are the
seed data's own uppercase convention (`ERP`/`MES`/`WMS`, matching
`seed/out/identity_truth.json`), while `services/ingestion/mapping.py`'s
table-routing convention is lowercase (`erp`/`mes`/`wms`, matching Kafka
topic names and docker-compose service names). A real canonical-fixture id
(`SKU-88429`) resolved as "unrecognized" until `mapping.py` was fixed to
`.upper()` the system name before calling the resolver — the resolver's
own tests all used uppercase directly, so they never caught the mismatch;
only end-to-end testing against a real mapped row did.

### CDC ingestion (`services/ingestion/`)

`consumer.py` (a `confluent_kafka.Consumer`, `enable.auto.commit=False`,
manual commit only after a message is fully applied — never skips ahead:
on a transient failure it retries the *same* message in place with
exponential backoff, so a partition's committed offset only ever advances
message-by-message, never past a not-yet-applied one) -> `mapping.py`
(declarative per-table `TableSpec`/`FieldSpec`, one `fac:` class instance
per table, `part`/`part_id` columns routed through the identity resolver)
-> `store.py` (`IngestionStore.apply_event`: idempotent upsert keyed by
`(source, table, pk)`, ordering by `(lsn, row-version)` tuple — LSN is
integer already in this Debezium version's JSON envelope (not the
"XXXXXXXX/XXXXXXXX" hex-slash form some docs show); `lsn.py`'s
`lsn_to_int` accepts both forms defensively).

**Bug caught empirically**: a DELETE CDC event carries no `after` row, so
the entity IRI to retract was originally derived only from a full
`MappedRow` (which is `None` on delete) — deletes silently left stale
triples behind. Fixed by separating entity-IRI resolution
(`mapping.resolve_entity_iri`, works from just a pk) from full-row mapping
(`mapping.map_row`); `store.apply_event` now takes `entity_iri` as an
explicit required parameter. Caught by an end-to-end smoke test against
the real running repository, not by unit tests against mocks.

**Failure handling** (F38): `PoisonMessage` (bad JSON, missing required
field, or a genuine SHACL rejection — HTTP 409 from a mapped row, as
opposed to an RDF4J outage) -> routed to Kafka topic `oo.ingestion.dlq`,
counted, offset committed so one bad message can never wedge the pipeline.
`RDF4JUnavailable` (connection error, 5xx, or 404 — the last one covers
the real startup race where `ingestion` starts consuming before `make
up`'s `bootstrap_rdf4j.py` step has created the repository) -> retried
in place with backoff (1s doubling to 30s cap), offset never committed.
Verified live: `tests/integration/test_cdc_ingestion.py`'s outage test
does a real `docker compose stop/start rdf4j` and proves the change made
during the outage still converges afterward.

`wms.transfers` **is** captured by CDC (its topic exists, `table.include.list`
includes it, ready for Phase 6 to reuse per ADR 0002) but is **not**
currently mapped into RDF — it is an action-execution artifact, not an
organic observed fact, until Phase 6's action runtime gives it that
meaning; `mapping.py` simply has no `TableSpec` for it, so
`consumer.py` skips those events (not poison, just unmapped).

Manual direct-DB edits (F37) need no special code: CDC observes every
committed row change regardless of which client wrote it, so a raw `psql
UPDATE` against a source DB produces the identical Debezium event (and
therefore the identical `oo:Observation` with no action-execution linkage)
as an application-driven change — verified via `_test/inventory/set`.

Health/DLQ visibility: `GET http://localhost:15484/health` (or
`services/ingestion/health.py` inside the container) — plain stdlib
`http.server` in a background thread, deliberately not FastAPI/uvicorn,
since the consumer's main loop is a tight synchronous `poll()` loop that
would conflict with an async framework's event loop in the same process.

### Debezium connectors (`contracts/cdc/v1/*-connector.json`)

One Postgres source connector per system (`plugin.name=pgoutput`,
`publication.autocreate.mode=filtered`, `snapshot.mode=initial`,
`tombstones.on.delete=false` — a delete arrives as one event with
`after=null` rather than an update+tombstone pair, simplifying the
consumer). Topic naming: `oo.<system>.public.<table>`. Registered
idempotently by `services/ingestion/register_connectors.py` (`PUT
.../connectors/{name}/config` is create-or-update), run by `make up`.

Each source-system Postgres role needs the `REPLICATION` attribute (`db/init/00_init.sh`,
applied idempotently to the already-running Phase 2 database live via
`ALTER ROLE ... WITH REPLICATION` rather than a destructive `make reset`,
then folded into `00_init.sh` for future fresh volumes) **and** a
dedicated `pg_hba.conf` entry — PostgreSQL's `pg_hba` "all" database
keyword does **not** match the "replication" pseudo-database (the docs are
explicit about this), so a replication-protocol connection is refused even
with a correct role/password until `host replication all all
scram-sha-256` is appended. Each role owns its own tables (created by its
own service), so `CREATE PUBLICATION` succeeds without superuser.

### Makefile

`make up` now also runs `register_connectors.py` and `bootstrap_rdf4j.py`
after `wait-healthy` (both idempotent, safe on every `make up`).
`make test-contracts` is implemented (`pytest tests/contracts`).
`make test-component` is a new (non-mandatory but phase3.md-item-6-required)
target for `pytest tests/component`. `make test` now runs `test-unit` +
`test-contracts` unconditionally, then `test-component` + `test-integration`
if the stack is reachable.

### Verification performed this phase

Every piece above was proven against the **real running stack**, not just
unit-tested against mocks: RDF4J repository creation, SHACL shapes-graph
loading, transactional 409 rejection with rollback verified via a
follow-up `ASK`; live Kafka Connect REST registration with all 3
connectors reaching `RUNNING`; a real WMS `_test/inventory/set` call
converging into RDF4J with `oo:Observation` provenance; direct
`IngestionStore.apply_event` idempotency/ordering proofs against live
RDF4J (duplicate, out-of-order-older, then a genuinely newer update, each
checked by re-querying the repository); a real `docker compose stop
rdf4j` / `start rdf4j` cycle proving no data loss. Two of the bugs listed
above (`.upper()` case mismatch, delete-retraction) were caught **only**
by this live end-to-end testing — neither was visible from code review or
from unit tests run against synthetic data alone.

### What Phase 4 (hot projections) / Phase 5 (decision service) need from here

- Named graphs and their IRIs: `services/common/rdf_graphs.py`. Entity IRI
  scheme: `https://example.local/factory/instance/{ClassName}/{localId}`;
  canonical part IRI: `.../instance/Part/{canonical_id}` (only Part is
  identity-resolved; every other id in this domain is already canonical).
- `oo:SourcePosition` resources (one per `(source, table, pk)`, IRI
  `https://example.local/oo/instance/pos/{system}/{table}/{pk}`) carry the
  latest applied LSN/version — Phase 5's evidence snapshot (spec 04/07/14
  R5) can cite these directly instead of re-deriving source positions.
- `oo:Observation` records (one per CDC event, `applied` true/false) are
  the full audit trail phase3.md item 5 asked for; query by
  `oo:sourceSystem`/`oo:sourceTable`/`oo:sourcePk` or via `prov:generated`
  to the entity IRI.
- The SHACL shape set is intentionally light on cross-entity referential
  integrity (see the `fac-core-shape.ttl` deviation above) — Phase 5's OPA
  policy layer is where "does this reference resolve" business rules
  belong, per R3.
- `wms.transfers` CDC topic already exists and is captured; Phase 6 only
  needs to add a `TableSpec` + decide what it means semantically (likely
  tied to `oo:ActionExecution`, whose shape already exists from this
  phase) — no new connector/topic work required.
- `IdentityResolver` is reusable as-is for any future need to resolve
  Part references outside the CDC path (e.g. a Phase 5 decision API
  accepting a source-local id from a caller).

### Known cross-phase test-isolation quirk (does not affect `make test`)

`pytest tests/model tests/contracts` (or any single `pytest` invocation
that collects **both** directories in **one process** — e.g. a bare
`pytest` with no args, since `pyproject.toml`'s `testpaths = ["tests"]`)
makes exactly two of `tests/model/test_bug_detection.py`'s Hypothesis
bug-injection parametrizations (`POLICY_THRESHOLD_LT`,
`SKIP_EXECUTION_RECHECK`) fail with "DID NOT RAISE AssertionError" —
`tests/model` alone is unaffected (21/21 passed, repeatedly verified).

Root cause, fully diagnosed (not a logic bug in either phase's code):
newer Hypothesis versions scan the *source of whatever modules are loaded
in the process* for literal constants and bias example generation toward
them (`.hypothesis/constants/` cache — confirmed present). Importing
`tests/contracts`'s real dependencies (`rdflib`, `pyshacl`, `httpx`, and
this phase's own modules) into the *same process* as
`reference_model`/`_machine.py` dilutes that constant pool, so the two
bugs whose minimal failing sequence depends on hitting one of
`reference_model`'s own specific threshold constants are less reliably
found within the fixed `max_examples=200` budget — even though
`derandomize=True` still makes the *random sequence itself* fully
deterministic. Verified exhaustively: not `random`/`uuid` state (checked
directly), not a duplicate-module import (checked `id()` identity), not a
deadline/health-check budget (`deadline=None` +
`suppress_health_check=[...]` does not fix it), not the Hypothesis example
database (`database=None` does not fix it). Confirmed as the documented
"local constants" feature via an **open, currently-unresolved** Hypothesis
upstream issue requesting an opt-out flag
(HypothesisWorks/hypothesis#4627) — there is presently no supported
setting to disable it.

**This does not affect this repository's own verification path**:
`make test` (and every `make test-*` target) runs each `tests/<dir>` as
its **own separate `pytest` subprocess** (see `Makefile` — `test-unit`,
`test-contracts`, `test-component`, `test-integration` are independent
recipe lines / sub-`make` invocations, never one combined `pytest` call),
so `tests/model` and `tests/contracts` never share a process there. Anyone
invoking bare `pytest` (or explicitly `pytest tests/model tests/contracts`
together) should expect this and run `pytest tests/model` separately if
those two specific parametrizations matter in isolation.

## Phase 4 — Hot projections

Tag `poc-v0.4-projections`. Spec: `docs/experiment/spec/01` (H6), `04`
(PostgreSQL hot projections, consistency model), `07` (projection rebuild),
`08` (performance methodology), `09` (F26/F27), `14` (R8).

### Ports

| Service | Host port | Notes |
|---|---|---|
| `services/projection_builder` health | 15485 | `GET /health` — build counters, F38-style visibility |

### Design: poll-based, full-rebuild-every-cycle

`services/projection_builder/main.py` runs as a docker-compose service
(shared root `Dockerfile`, `command: python3 -m services.projection_builder.main`),
polling every `OO_PROJECTION_POLL_INTERVAL_S` (default 3s — phase4.md item
1's "triggered by ingestion updates or a short poll", short-poll option
chosen over wiring a second Kafka consumer group off the ingestion topics).
Each cycle calls `services/projection_builder/builder.py::build_all`, which:

1. Runs the SPARQL queries in `contracts/projections/v1/*.yaml` against
   RDF4J (never against ERP/MES/WMS's Postgres databases — the ONLY input
   is the semantic core, per item 1's explicit requirement).
2. Computes all four projections in pure Python
   (`services/projection_builder/compute.py`) from the raw SPARQL rows.
3. `TRUNCATE`s and re-`INSERT`s all four `ontology_hot` tables inside ONE
   transaction (`services/projection_builder/writer.py`), so a concurrent
   hot reader under READ COMMITTED only ever sees the fully-old or
   fully-new state, never a half-rebuilt one.

`build_all` is the exact same function used by the live poll loop, `make
rebuild-projections` (`services/projection_builder/rebuild.py`), and the
differential/rebuild tests — "one poll tick" and "full rebuild from
scratch" are provably the same code path, which is what item 3's projection
rebuild requirement is really asking for.

**Why shortage/incoming aggregation is Python, not one SPARQL query**: the
"incoming before deadline" sum is a per-work-order CORRELATED filter (only
purchase-order lines whose PurchaseOrder's `expectedAt` is `<=` THIS work
order's `plannedStart` count) — SPARQL 1.1 has no clean way to express a
`GROUP BY` whose threshold varies per outer row without re-running the
subquery per row. Forcing that into one mega-query would be exactly the
"business rules better represented in policy code than graph constraints"
misuse R3 warns against. The four `work_order_risk.yaml` queries pull RAW
FACTS from RDF4J (work orders, requirements, inventory, incoming PO lines);
`compute.py::compute_work_order_risk` re-implements
`reference_model/derive.py`'s exact formula independently (not a shared
import), so the differential test is a genuine two-implementation
comparison.

### Phase 3 gap found and fixed: BomRequirement/PurchaseOrderLine were never linked to their parent

`services/ingestion/mapping.py`'s `bom_requirements` and
`purchase_order_lines` `TableSpec`s never mapped their own `work_order_id`/
`po_id` FK columns — `fac:hasRequirement` (WorkOrder->BomRequirement) and
`fac:hasLine` (PurchaseOrder->PurchaseOrderLine) were declared in
`fac-core.ttl` since Phase 3 but had NO writer, so work_order_risk had no
way to find a work order's requirements or a PO's lines via SPARQL.

**First fix attempt (reverted, kept as a documented cautionary tale)**: an
`inverse_ref` `FieldSpec` kind that wrote the triple from the REFERENCED
parent's subject (`WorkOrder --hasRequirement--> BomRequirement`). This is
unsound: `services/ingestion/store.py::apply_event`'s upsert-by-subject
retracts a subject's ENTIRE triple set whenever THAT subject's own row is
reprocessed. Since `work_orders`/`purchase_orders` are independent CDC
streams from `bom_requirements`/`purchase_order_lines`, any later
reprocessing of the PARENT's own row (a legitimate, ordinary event) silently
wipes the backlink — and whether this manifests depends on CDC snapshot
delivery order between the two tables, which varies non-deterministically
run to run. Empirically: `fac:hasRequirement`/`fac:hasLine` populated fully
(201/1997 triples) on one `make reset && make seed`, and came back at
201/**0** on the very next one with identical code and `SEED=42`.

**Actual fix**: a forward `ref` (the row's OWN subject -> its owning
parent) — `fac:workOrder` on `BomRequirement` and `fac:purchaseOrder` on
`PurchaseOrderLine`, using the SAME `"ref"` `FieldSpec` kind every other
FK-like column already uses. This is safe under any delivery order because
the triple's subject is the CHILD row's own entity — it only gets
retracted/rewritten when THAT row's own CDC event is reprocessed, exactly
matching the upsert semantics `store.py` already implements correctly for
every other field. `fac:hasRequirement`/`fac:hasLine` are kept declared in
`fac-core.ttl` as `owl:inverseOf` documentation only (RDF4J's `ShaclSail`
runs no OWL inference, so this has zero runtime effect) — a future phase
adding real inference would need to assert these explicitly, not assume
they come for free. The `inverse_ref` `FieldSpec` kind was removed from
`services/ingestion/mapping.py` entirely rather than left available for a
future author to fall into the same trap.

Verified: `fac:workOrder`/`fac:purchaseOrder` triple counts (201/1997)
matched the source row counts across every subsequent `make reset && make
seed` performed during this phase's implementation.

### Second bug found (via `make rebuild-projections` against the real seeded dataset, not caught by any hand-written fixture): duplicate BomRequirement rows for the same part

MES's `bom_requirements` table has no `UNIQUE(work_order_id, part_id)`
constraint. The `SEED=42` generated dataset genuinely produces at least one
work order (`WO-0146`) with TWO separate requirement rows for the SAME part
(`PX-0251`) — not a theoretical edge case, an empirical one. The original
`compute_work_order_risk` evaluated each requirement row independently
against the SAME available/incoming supply (double-counting it) and,
whenever that work order became at-risk, `compute_transfer_candidates`
emitted the SAME `(work_order, part, source_warehouse)` `candidate_id`
twice — a Postgres `UniqueViolation` on `transfer_candidates_pkey` that
first surfaced from `make rebuild-projections`, not from any test written
against the canonical fixture (which only has one requirement per work
order). Fixed by grouping requirement rows by PART first (summing
`qty` across duplicates) before computing shortage per part — matching
`reference_model.state.WorkOrder.requirements`'s own `part -> qty` MAPPING
semantics, which implicitly assumes exactly this kind of de-duplication.
Regression-tested without Docker in
`tests/component/test_projection_compute.py` (synthetic duplicate-row
input, asserts both the summed shortage AND that no duplicate
`candidate_id` is ever produced).

### Hot projections (`contracts/projections/v1/*.yaml`, `services/projection_builder/`)

Four tables in `ontology_hot` (`services/projection_builder/schema.sql`):

- **`work_order_risk`**: `work_order_id`, `warehouse`, `shortage`,
  `at_risk`, `severity` (`CRITICAL` while at-risk, `MITIGATED` once
  shortage hits zero — `severity` has no reference_model equivalent, it is
  a projection-only UI-friendly label derived purely from `at_risk`).
- **`transfer_candidates`**: per (at-risk work order, shortfall part,
  candidate source warehouse != the work order's own warehouse with
  `available > 0`), `candidate_quantity = min(available_at_source,
  shortfall)`. Descriptive only — no policy/authorization evaluation (R3;
  that is Phase 5's OPA layer).
- **`current_inventory`**: direct, un-aggregated `fac:InventoryLot` read —
  the one projection whose SPARQL definition needs no Python aggregation.
- **`action_eligibility_summary`**: pure aggregation over this cycle's
  `work_order_risk` + `transfer_candidates` results (no new SPARQL query);
  `mitigation_feasible = (not at_risk) or (total_candidate_quantity >=
  shortage)`.

Every row carries (`services/projection_builder/writer.py`):
`source_positions` (JSONB list of `{system, table, pk, lsn, version,
observed_at}` for every contributing entity, looked up from `oo:SourcePosition`
via `services/projection_builder/provenance.py::CLASS_TO_SOURCE` —
deliberately excludes `fac:Part`, since `oo:SourcePosition` for `erp.parts`
is keyed by ERP's pre-resolution LOCAL id, not the canonical id these rows
reference), `projection_definition_name/version/sha256` (sha256 computed
over the RAW BYTES of the matching `contracts/projections/v1/*.yaml` file
at load time — never hardcoded, so it can't drift from the file on disk),
`ontology_contract_version` (`services/common/contract_versions.py`,
currently the constant `"v1"` — matches the single ontology contract
directory that exists so far), `computed_at` (wall-clock build time), and
`as_of` (the LATEST `observed_at` among contributing source positions — a
row's evidence freshness, not when it happened to be recomputed).

### Freshness (F26) and consistency (F27)

`services/projection_builder/freshness.py`: FRESH/STALE is evaluated at
READ time (`evaluate(as_of, now, max_age_s=5)`), never stored as a column —
a column would itself go stale as wall-clock time passes without a new
build. This is also what makes F26 testable without a real 30-second wait:
`tests/integration/test_projection_staleness.py` pushes a real row's
`as_of` back via direct SQL and asserts `evaluate()` reports STALE
immediately.

`services/projection_builder/consistency.py` (F27): every row's
`content_hash` (`services/projection_builder/hashing.py::row_content_hash`)
is a sha256 over exactly that table's declared `BUSINESS_COLUMNS` — never
`computed_at`/`as_of`/`source_positions`/the three
`projection_definition_*` columns/`ontology_contract_version` (these are
documented as EXCLUDED per item 3's "documented exclusions for
timestamp/technical columns", and the SAME `BUSINESS_COLUMNS` map is reused
by `hashing.py::table_hash` for the whole-table rebuild-hash comparison).
`tests/integration/test_projection_consistency.py` tampers a business field
directly via SQL (bypassing `writer.py`, which always recomputes
`content_hash` together with the fields it hashes) and asserts the checker
catches the mismatch.

### `make rebuild-projections` / `make bench`

`rebuild-projections` (`services/projection_builder/rebuild.py`) applies
`schema.sql` idempotently, hashes all four tables (`hashing.py::table_hash`,
business columns only), calls `build_all`, hashes again, and prints
MATCH/MISMATCH per table (exits 1 on any mismatch) — the pytest authority
for the same claim is `tests/integration/test_projection_rebuild.py`.

**Concurrency finding**: `build_all` must run on a connection WITHOUT
`autocommit` (the default) when called directly by a test/script, because
the LIVE poll-loop container is continuously doing the same TRUNCATE+INSERT
cycle every few seconds. Under `autocommit=True`, each statement is its own
transaction, so the live poller's `TRUNCATE` can land in between two of a
second caller's individual `INSERT`s and produce a spurious
`UniqueViolation` — caught empirically when `tests/integration/`'s shared
`ontology_hot_conn` fixture (autocommit, kept that way for read-polling
convenience elsewhere) was reused to call `build_all` directly.
`TRUNCATE`'s `ACCESS EXCLUSIVE` lock correctly serializes two PROPERLY
TRANSACTIONAL full-rebuilds against each other (second blocks until the
first commits) — `rebuild.py` already opened its connection without
autocommit by default; only the test needed a dedicated connection.

`bench` (`tests/performance/bench_phase4.py`) measures `work_order_risk`
point reads warm (one reused connection) and cold (fresh connection per
sample), plus the H6 counter-test (the equivalent requirement+inventory
SPARQL query run directly against RDF4J for the same work order). Writes
`experiments/exp-000/results/bench-phase4.json` with environment metadata
(OS/CPU/RAM via `sysctl`/`platform`, docker version). The SLO
(`hot_read_p95_ms` from the LOCKED `experiments/exp-000/manifest.yaml`,
never redefined here) is evaluated against the WARM p95 specifically (the
steady-state hot-path number H6 is actually claiming); COLD is reported
alongside for transparency but is not the pass/fail gate. Measured on this
machine: warm p95 ≈0.2-0.3ms, cold p95 ≈5-12ms (one 199ms cold outlier
observed once, attributable to host contention during implementation, not
reflected in the SLO gate), semantic-core-direct SPARQL warm p95 ≈1.1-1.3ms
— i.e. the projection's warm read is roughly 4-6x faster than querying
RDF4J directly for the same information, which is the whole point of H6's
counter-test. **SLO: PASS** (measured warm p95 well under the 200ms
threshold on every run performed).

### Environment finding: this session's shared Docker daemon was reset by an external process throughout Phase 4 implementation

Repeatedly observed (`docker ps --format '{{.RunningFor}}'` showing ALL
`oo-poc-*` containers recreated simultaneously, at a fresh "N seconds/
minutes ago", with no `make reset`/`docker compose down` issued by this
agent in between) during this implementation session: the ENTIRE `oo-poc`
compose project got torn down and reseeded from an external source roughly
every 2-8 minutes, independent of anything this agent did. Symptoms this
caused, all eventually traced to it (not to Phase 4 code) and NOT
representative of any lasting defect: `hasLine`/`hasRequirement` (later
`workOrder`/`purchaseOrder`) counts fluctuating between 0 and the full
expected value across successive checks; `work_order_risk` briefly showing
`shortage=0` for WO-42 immediately after a wipe (RDF4J re-empty, requirement/
incoming-line data not yet re-ingested, so the shortage formula correctly
computed 0 from an incomplete input — not a compute.py bug); two
`test_projection_differential.py` runs failing with "never converged"
because the entire stack was mid-reset under the running test. The FINAL
`make test` run recorded in this section's summary (see phase4-report.md)
was captured in a confirmed-stable window (`docker ps` showed no container
recreation for 3+ minutes before AND immediately after the run). Anyone
re-running this phase's suite against the SAME shared host should expect
occasional unrelated flakiness from this cause and should verify container
uptimes before attributing a failure to the code.

### What Phase 5 (decision service) needs from here

- Hot-projection reads are plain psycopg SELECTs
  (`services/projection_builder/reader.py`) — there is no HTTP API for
  `ontology_hot` yet; the Decision API is exactly the thing Phase 5 adds on
  top of this (per `04_architecture.md`'s component diagram, "Decision API
  / MCP" sits above "PostgreSQL hot state").
- `transfer_candidates` is intentionally policy-free (R3) — Phase 5's OPA
  layer is where "is this candidate actually approvable" belongs.
- `freshness.evaluate(as_of, now, max_age_s)` is reusable as-is for a
  Phase 5 evidence-freshness gate (F08/staleness policy).
- `services/common/contract_versions.ONTOLOGY_CONTRACT_VERSION` is the
  single source for the ontology-version string Decision records will need
  to cite (H1's required field list).
