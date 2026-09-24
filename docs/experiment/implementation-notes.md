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

### Environment finding, CORRECTED (see "Phase 4 fix" section below): the stack resets were self-inflicted, not an external process

This section originally claimed "this session's shared Docker daemon was
reset by an external process throughout Phase 4 implementation." **That
claim was wrong and is corrected here** (docs/experiment/briefs/phase4fix.md
item 3): a later independent verification watched the stack for 12 minutes
with no test process running and observed ZERO container recreations,
ruling out any external actor. The real cause of the container-recreation
churn observed during Phase 4 implementation was this repository's OWN
`tests/integration/test_seed_determinism.py`, which performs `make reset
&& make seed` TWICE via `subprocess.run` as part of its own test body —
and, at the time, `test_seed_determinism.py` ran as part of `make
test-integration`, i.e. inside plain `make test`. Any overlapping or
closely-spaced `make test` invocation during that implementation session
(this agent's own, run repeatedly while iterating) would have looked
EXACTLY like "something external is resetting the stack every few minutes,
with no `make reset` from me in between" — because the reset genuinely
did not come from that particular `make test` invocation, it came from a
DIFFERENT one (or from `test_seed_determinism.py`'s own second internal
reset firing again). The symptoms originally attributed to an external
process (`hasLine`/`hasRequirement`/`workOrder`/`purchaseOrder` counts
fluctuating, `work_order_risk` briefly showing `shortage=0`,
`test_projection_differential.py` failing with "never converged") are all
consistent with this self-inflicted cause and needed no other explanation.
See the "Phase 4 fix" section below for the actual fix: destructive tests
now live in `make test-destructive`, never inside `make test`.

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

## Phase 4 fix — test-suite stability

Tag `poc-v0.4.1-stable`. Brief: `docs/experiment/briefs/phase4fix.md`. No
new ports/services — this phase only touches Makefile targets, one new
ingestion module, and test isolation.

### Root cause (with evidence)

The reported failure (`test_wms_change_converges_to_rdf4j_with_provenance`:
"WMS change did not converge... `before` had NO fac:onHand for LOT-A-PX17")
had two independent contributing causes, both confirmed empirically:

**1. `_wait_for_ingestion_caught_up()` was a false-positive detector, not a
convergence proof.** It polled the ingestion health endpoint's
`messages_consumed` counter and declared "caught up" the moment two
consecutive 2-second samples were equal. That condition is satisfied just
as happily by "nothing has reached Kafka yet" as by "the backlog has been
drained." Reproduced directly while validating this fix: querying real
Kafka consumer-group lag immediately after `make seed`'s inserts finished
gave, sample by sample. `lag total=0 per-topic={}` (topics did not exist
yet — Debezium had not read the new WAL records), then on the very next
2-second sample `lag total=6921` (the real backlog had appeared). A
counter-based or single-sample check taken at that first instant would
declare convergence while the canonical fixture (LOT-A-PX17) is still
completely absent from RDF4J — exactly the reported symptom.

**2. `test_seed_determinism.py` ran `make reset` twice from inside `make
test`,** and an independent verification's `make bench` run immediately
after `make test` hit the stack mid-reconvergence (`bench` failed with "no
work_order_risk row for WO-42 even after a build"). This is also what
Phase 4's implementation-notes section had wrongly blamed on "an external
process resetting the shared Docker daemon" (corrected above) — a 12-minute
watch with no test process running showed zero container recreations; the
resets were this repository's own destructive test running as part of a
supposedly non-destructive target.

**Discarded alternative, recorded for anyone tempted to reach for it
again:** comparing each Debezium replication slot's `confirmed_flush_lsn`
against Postgres's `pg_current_wal_lsn()` looks like the authoritative way
to know a connector has caught up, but `pg_current_wal_lsn()` is
CLUSTER-WIDE — `services/projection_builder`'s own poll-every-3s
TRUNCATE+INSERT cycle against the unrelated `ontology_hot` database keeps
advancing it continuously, so a slot's flush position never converges to
"current" even when the connector has captured 100% of its own tables'
changes. Measured on a stack that was demonstrably fully converged
(ingestion health showed `messages_consumed == messages_applied`): ~190MB
of "lag" by that metric. Abandoned in favor of ground-truth checks (see
below).

### Design: a single readiness contract (`services/ingestion/readiness.py`)

New module, shared by `make wait-converged`
(`services/ingestion/wait_converged.py`, a thin CLI wrapper) and
`tests/integration/test_cdc_ingestion.py`'s `_wait_for_ingestion_caught_up`.
Checks run in order, each with its own timeout and progress logging, and
the function raises `ConvergenceTimeout` with exactly what's still missing
on failure (never fakes convergence):

1. **Connectors + tasks RUNNING** (Kafka Connect REST `/connectors/{name}/status`).
2. **Ingestion consumer lag == 0** against each CDC topic's freshly-fetched
   current high-watermark (`confluent_kafka` `AdminClient` +
   `Consumer.get_watermark_offsets`), required stable across two
   consecutive 2-second samples. This is real Kafka lag, not a counter
   proxy — but it is still only defense-in-depth, not the sole correctness
   guarantee (see next point).
3. **RDF4J contains the canonical fixture** (WO-42 exists; LOT-A-PX17 has a
   `fac:onHand` fact) — `expect_data=True` only (skipped right after a bare
   `make up`/`make reset`, before any seed has run, when this could never
   be satisfied). This is the LOAD-BEARING check: even if step 2's
   high-watermark snapshot was itself sampled too early (Debezium hadn't
   read the new WAL yet), this step just keeps polling its own generous
   timeout until the real data shows up, which is what actually fixes the
   reported bug.
4. **`ontology_hot.work_order_risk` has a WO-42 row** — closes the `make
   bench` failure mode directly.

`CDC_TOPICS` for step 2 is derived from
`services.ingestion.consumer.all_topics()` itself, not a hand-maintained
duplicate list. First cut duplicated the list from the Debezium connector
configs' `table.include.list`, which includes `wms.transfers` —
`consumer.py`'s own `TABLES` dict deliberately excludes `transfers`
(mapping.py: "transfers ... deliberately NOT mapped"), so the ingestion
consumer group never subscribes to that topic and never commits an offset
for it. That produced a PERMANENT phantom lag of 9 that could never drain
(nothing ever consumes it), caught empirically before this ever reached a
test run.

`register_connectors.py` now calls `readiness.connectors_running()` after
registering, closing a real (if narrow) race: a PUT to
`/connectors/{name}/config` only means Kafka Connect accepted the config,
not that the task has started and created its Postgres replication slot —
and `make seed` can run as a separate, later `make` invocation the moment
`make up` returns.

`make reset` (`docker compose down -v`) drops the Postgres AND RDF4J named
volumes. Kafka and Connect have **no named volume at all** in
docker-compose.yml — verified: `docker volume ls` before a reset showed
only `oo-poc_oo-poc-pgdata` and `oo-poc_oo-poc-rdf4j-data`; a plain
container recreation already destroys their broker/internal-topics state
every time regardless of `-v`. Confirmed live: right after `make reset`,
`bootstrap_rdf4j.py` printed "creating repository 'oo'" (it did not exist —
proving the RDF4J volume was truly wiped) and the Kafka topic list was
empty (proving Kafka/Connect state doesn't survive either).

### Deviations

- `tests/integration/test_seed_determinism.py` moved OUT of
  `test-integration`/`make test` into a new `make test-destructive` target
  (aliased `make test-determinism`) — never runs concurrently with
  anything else touching the shared stack.
- `tests/integration/test_cdc_ingestion.py::test_wms_change_converges_to_rdf4j_with_provenance`
  was retargeted from the canonical fixture (LOT-A-PX17 / SKU-88429 / WH-A)
  to a synthetic marker (`SKU-CDC-CONVERGENCE-TEST` / `WH-C`), matching the
  convention `test_wms_concurrency.py` / `test_wms_idempotency.py` /
  `test_wms_faults.py` / the RDF4J-outage test already use. Found while
  running the acceptance sequence's mandated repeated `make test`
  invocations: the original test permanently incremented LOT-A-PX17's
  `on_hand` by 1 on every run (via `_test/inventory/set`, an unconditional
  overwrite, not an idempotent replay), which broke
  `test_canonical_scenario.py::test_step4_transfer_60_units_wh_b_to_wh_a`'s
  absolute-end-state assertion (`after_a["on_hand"] == 80`) on the second
  `make test` run within the same stack lifetime. Not previously visible
  because nothing had run `make test` back-to-back without an intervening
  reset until this fix's own acceptance criteria required exactly that.
- `bench_phase4.py` now calls `readiness.wait_for_converged()` when
  `work_order_risk` has no WO-42 row yet, instead of failing immediately;
  only times out (exit 2) if the pipeline genuinely never converges.

### Acceptance run (this session, sequential, nothing overlapping)

```
make reset && SEED=42 make seed && make test && make bench && make test-destructive && make test && make bench
```
then `make test` three more times. All green, every pytest summary line:

| Step | Result |
|---|---|
| `make reset` | clean (connectors RUNNING, RDF4J repo freshly created, Kafka topics empty) |
| `SEED=42 make seed` | converged in ~90s (kafka lag drained 6921 -> 0, canonical fixture + WO-42 row confirmed) |
| `make test` (1st) | `tests/model`: 21 passed; `tests/contracts`: 19 passed; `tests/component`: 15 passed; `tests/integration`: 36 passed |
| `make bench` (1st) | SLO PASS, warm p95 = 0.304ms (threshold 200ms) |
| `make test-destructive` | `1 passed` in 224.72s (two full internal reset+seed cycles) |
| `make test` (2nd) | 21 / 19 / 15 / 36 passed |
| `make bench` (2nd) | SLO PASS, warm p95 = 0.295ms |
| `make test` (flake check 1/3) | 21 / 19 / 15 / 36 passed |
| `make test` (flake check 2/3) | 21 / 19 / 15 / 36 passed |
| `make test` (flake check 3/3) | 21 / 19 / 15 / 36 passed |

Zero flakiness observed across all 5 `make test` invocations in this
session.

### What later phases need from here

- `make seed`/`make reset` now block until the pipeline has genuinely
  converged — no later phase needs its own ad hoc "is the stack ready"
  polling; call `make wait-converged` (or import
  `services.ingestion.readiness.wait_for_converged`) instead of
  reinventing a readiness check.
- Any FUTURE destructive test (one that runs `make reset`/`down` itself)
  belongs in `make test-destructive`, never in `make test` — this is now
  the established convention, not just this one test's fix.
- Any FUTURE test that mutates WMS/ERP/MES state via a `_test/*` endpoint
  should target a synthetic, non-canonical entity (part/warehouse/etc.),
  matching the pattern every test in `tests/integration/` other than the
  original `test_wms_change_converges_to_rdf4j_with_provenance` already
  followed — never the canonical incident fixture (PX-17 / WO-42 /
  LOT-A-PX17 / LOT-B-PX17 / WH-A / WH-B), which `test_canonical_scenario.py`
  and this phase's own readiness contract both assert absolute state
  against.

## Phase 5 — Decision service + gates

Tag `poc-v0.5-gates`. Brief: `docs/experiment/briefs/phase5.md`. Spec: 01
(H1/H2/H13/H14), 03, 04, 05, 06, 08, 09, 11, 14.

### Ports

| Service | Host port | Notes |
|---|---|---|
| OpenFGA HTTP API | 15481 | `memory` datastore engine — wiped on every container restart, see below |
| OPA server | 15482 | loads `contracts/policies/v1` as a mounted read-only bundle directory (`--watch`) |
| `services/decision_service` | 15410 | FastAPI; endpoints below |

### OpenFGA/OPA have no docker-level healthcheck

Both images (`openfga/openfga`, `openpolicyagent/opa`) have **neither a
shell nor curl/wget** (verified: `docker run --entrypoint /bin/sh ...` ->
"no such file or directory"), so a `HEALTHCHECK CMD`/`CMD-SHELL` cannot run
*inside* either container at all — there is nothing to exec. Rather than
fake one, `docker-compose.yml` declares no `healthcheck:` for these two
services, and `make wait-healthy` was rewritten from a bash/grep loop into
`services/common/wait_healthy.py`, which treats a service with **no
configured healthcheck** as ready once its `State` is `running` (parsed from
`docker compose ps --format json`). Real API readiness for OpenFGA is
instead proven from the HOST, in `services/decision_service/bootstrap_openfga.py`,
by polling the real `GET /healthz` endpoint (`{"status":"SERVING"}`,
verified empirically) before writing anything — OPA's own bundle-load
startup was measured to be sub-second and needs no separate wait.

### OpenFGA bootstrap: `fga model transform` (docker CLI), not a hand-written DSL parser

`services/decision_service/bootstrap_openfga.py` shells out to the
`openfga/cli` docker image's `model transform --file model.fga
--output-format json` (a pure local-file transform, no network needed) to
get the JSON authorization-model form OpenFGA's HTTP API actually accepts,
then POSTs it directly via httpx. Idempotent within one running container's
lifetime: reuses an existing `oo-poc` store by name (`GET /stores`), writes
a new model VERSION every run (harmless — OpenFGA keeps every version;
Checks use the latest), and tolerates "tuple already exists" (HTTP 400,
`write_failed_due_to_invalid_input`) when re-applying `tuples.yaml`'s
fixture tuples. **OpenFGA runs with the `memory` datastore engine** — a
container restart wipes the store/model/tuples entirely (verified via the
F23 dependency-outage test below), so `make up` always re-runs this
bootstrap step, and `services/decision_service/app.py`'s `_current_store_id()`
deliberately does **not** cache the resolved store id across requests (see
below).

### Authorization model (`contracts/authorization/v1/model.fga`)

`user`, `agent` (with a `principal: [user]` relation — the
agent-on-behalf-of-user delegation link, openfga.dev's "agents as
principals" pattern per `contracts/SOURCES.md`), `region` (`planner`/
`supervisor`), `warehouse` (`in_region: [region]`, `planner`/`supervisor`
either direct or inherited via `in_region`, `junior_planner`, `agent_grant:
[agent]`, `can_transfer_inventory: planner or junior_planner or
agent_grant`, `can_approve_large_transfer: supervisor`).

**Deviation from a first draft, found while writing `tests.yaml`**:
`junior_planner` was originally NOT unioned into `can_transfer_inventory`
(reasoning: "let policy-adjacent code enforce propose-vs-approve"). This
contradicted `03_domain_scenario.md`'s own text ("junior_planner: can
propose") and made `08_test_strategy.md`'s "junior denied protected
approval" test impossible to write meaningfully (a junior denied
`can_transfer_inventory` outright would never even reach an approval
decision to be denied). Fixed by unioning `junior_planner` into
`can_transfer_inventory` — the ONLY relation junior lacks is
`can_approve_large_transfer`, which is exactly where 08's test list draws
the line.

Verified via the real `fga model test` runner
(`contracts/authorization/v1/tests.yaml`, `tuple_file: tuples.yaml`): 8/8
tests, 12/12 checks passing (`docker run --rm -v
contracts/authorization/v1:/app openfga/cli:latest model test --tests
/app/tests.yaml`). All three ActionTypes bind authorization to a
**warehouse** (the model's only typed object with authority relations) —
`transfer_inventory` uses its own `source_warehouse` parameter directly;
`expedite_purchase_order`/`reschedule_work_order` resolve the relevant
warehouse from evidence (a PO's first line's destination-warehouse, a work
order's own warehouse) rather than needing separate `purchase_order`/
`work_order` FGA types (`services/decision_service/authz.py::resolve_object`).

### Policy bundle (`contracts/policies/v1/`)

`transfer_inventory.rego` (package `factory.inventory.transfer`) implements
`03_domain_scenario.md`'s policy example exactly (quantity <= 100 AND
remaining >= safety_stock AND not quarantined -> allow; above threshold ->
require_approval with a `can_approve_large_transfer` obligation; quarantine
or stale evidence -> deny, the latter ALSO carrying a `refresh_evidence`
obligation). `expedite_purchase_order.rego`/`reschedule_work_order.rego` are
simpler but real (terminal-status deny, threshold/priority ->
require_approval) — see "Scoping decision" below for why they get less
test rigor. `data.json` is the safety_stock source of truth
(`{part: {warehouse: qty}}` + `default_safety_stock`), read by BOTH OPA (as
part of its mounted bundle, versioned by the same `opa.sha256`) and
`services/decision_service/evidence.py` directly (the same file, not a
copy) — `safety_stock` is modeled as required EVIDENCE per 05's closed-world
closure example, resolved from this file, not silently defaulted inside
Rego.

**Rego gotcha found empirically**: a rule defined only as two mutually
exclusive `if` bodies (`x := A if cond` / `x := B if not cond`) is
UNDEFINED — not `B` — when a field the `cond` itself reads is entirely
absent from `input` (e.g. `input.evidence` missing altogether, not just one
field). `default x := B` fixes it. Caught by
`transfer_inventory_test.rego::test_missing_evidence_block_entirely_is_non_allow`:
`obligations` (and therefore the whole `result` object) failed to bind at
all until `approval_obligation`/`refresh_obligation` were rewritten with
`default ... := []`. `opa test --fail-on-empty`: 20/20 passing.

### ActionType contracts (`contracts/actions/v1/*.yaml`)

`transfer_inventory` (full rigor — see below), `expedite_purchase_order`,
`reschedule_work_order`. `context.work_order_id` is accepted in the
**propose request**, not as a formal ActionType parameter — it exists
purely so `evidence.py` can attach `linked_work_order_risk` (informational,
not `closure.required`); an action can legitimately be proposed without
linking it to a specific at-risk work order (e.g. proactive rebalancing).

### Decision service (`services/decision_service/`)

`propose_flow.py::propose()` implements 06's algorithm with one explicit,
documented ordering deviation: **all contract versions are captured up
front** (implied by 06's own "create PROPOSED(evidence, current contract
versions)"), evidence is frozen and closure-checked FIRST (before
authz/policy — consistent with 04's trust-boundary list), then authz, then
policy, and **the SHACL-validated RDF4J write happens EXACTLY ONCE, at the
very end**, for whatever terminal status was reached — never once per gate.
RDF4J's add-only statement API has no partial in-place update primitive
suited to a decision built up over several stages; one atomic write at the
end means an `INSUFFICIENT_EVIDENCE`/`DENIED_*` decision is exactly as
complete (all 12 SHACL-required fields) as an `APPROVED` one (H1). "Authenticate
actor" (04/06) has no separate identity-provider step — there is no login/
session system anywhere in this repo through Phase 4, and the canonical
fixture's `actors:` block only ever declares role/region ASSIGNMENTS, never
credentials; an actor's identity is accepted as asserted by the caller and
enforced entirely through what OpenFGA does/doesn't grant that principal.

**Version fields are content-addressed** (`services/decision_service/manifest.py::content_addressed`),
matching 05's exact example (`"inventory-policy@sha256:..."`) rather than a
bare `"v1"` — `ontologyVersion`/`shapeSetVersion`/`authorizationModelVersion`/
`policyBundleVersion` are all `"v1@sha256:<hash-of-the-real-files-on-disk>"`.
`actionVersion` stays a plain `xsd:integer` (the ontology's existing
datatype constraint) — its content-addressing is the `contracts/manifests/current.json`
`actions.<name>.sha256` entry instead.

**Fail-closed (F22-F24)**: RDF4J unreachable during evidence
gathering/write raises `httpx.HTTPError`/`psycopg.Error`, caught by
`app.py` and returned as HTTP 503 + a `proposal_attempt_failures` Postgres
row (never a Decision — H1's completeness metric is only over decisions
that actually exist) — no governed decision object is even attempted, since
one is genuinely impossible to write. OpenFGA/OPA unreachable are caught
INSIDE `authz.check()`/`policy.evaluate()` (never raised) and surfaced as
`outcome: "UNAVAILABLE"` on the gate-result resource, which the propose
pipeline treats as a normal deny (`DENIED_AUTHORIZATION`/`DENIED_POLICY`) —
still a complete, queryable Decision record, just with an explicit
unavailable-vs-actually-denied distinction (acceptance criterion 11:
"explicit unavailable/pending/unknown state, not fabricated certainty").

**`_current_store_id()` is deliberately NOT cached** across requests (one
extra `GET /stores` call per proposal, negligible next to the `check()` call
that follows it) — found empirically via the F23 outage test: OpenFGA's
`memory` datastore means a restart mints a BRAND NEW store id, and a cached
old id would silently 404 forever afterward with no way to self-heal short
of restarting `decision_service` itself.

**SHACL `sh:class prov:Agent` needs an EXPLICIT triple, not a two-hop
`rdfs:subClassOf` chain**: `oo:HumanActor rdfs:subClassOf prov:Agent`
(one hop) satisfied RDF4J's `sh:class` check, but `oo:SoftwareAgent
rdfs:subClassOf prov:SoftwareAgent` (needing a SECOND hop,
`prov:SoftwareAgent rdfs:subClassOf prov:Agent`, never asserted anywhere
since this repo never imports real PROV-O axioms) did not — the very first
agent-actor decision write got a real 409. Fixed by asserting `rdf:type
prov:Agent` (and `prov:SoftwareAgent` for agents) EXPLICITLY on every actor
node in `rdf_writer.py::_actor_node`, rather than relying on any inferred
subclass chain (matches the established "RDF4J's ShaclSail runs no OWL
inference" finding from Phase 3, generalized: even a single un-asserted
`rdfs:subClassOf` link in a multi-hop chain breaks a `sh:class` check).

**`conformance_outcome` must be set BEFORE the first RDF4J write, not
after**: the graph sent to RDF4J is built from `record` as it stood AT WRITE
TIME. An earlier version set `record.conformance_outcome = record.conformance_outcome
or "CONFORMS"` only in the SUCCESS branch after `write_decision()` already
returned — meaning the committed graph itself never carried a
`oo:ConformanceCheck` resource for the (overwhelmingly common) CONFORMS
case, even though Postgres and the HTTP response both showed it correctly.
Caught by `tests/integration/test_forensic_queries.py` querying RDF4J
directly (H13 query 1) and finding no `conformanceOutcome` binding.

**Approval (`rdf_writer.py::record_approval`)** transitions
`REQUIRES_APPROVAL` -> `APPROVED` via one atomic SPARQL 1.1 Update
(`DELETE {...} INSERT {...} WHERE {}`, `Content-Type: application/sparql-update`)
against RDF4J's `/statements` endpoint — verified empirically to still be
SHACL-validated (a would-be two-statuses-at-once state 409s and rolls back,
exactly like `add_turtle`). `RDF4JClient.update()` is the new client method
this needed; `add_turtle()` alone cannot change `oo:status` in place since
it is purely additive.

### Security review finding, fixed during implementation: SPARQL injection (F31)

A security review flagged `services/decision_service/evidence.py`'s
warehouse-existence ASK query building a SPARQL literal via f-string
interpolation of a caller-supplied `destination_warehouse` value —
exactly the F31 "tool parameter injection" surface. Fixed with TWO
independent layers: (1) **primary** —
`services/decision_service/schemas.py`'s `ProposeRequest`/`ApproveRequest`
validate every identifier-shaped value (`action_type`, `actor.id`, every
string anywhere inside `parameters`/`context`, `approver_id`,
`decision_content_hash`) against a strict `^[A-Za-z0-9_-]{1,64}$` pattern
(or a 64-char hex pattern for the hash) BEFORE the request can reach
anything — a non-matching value is HTTP 422 (F01, zero effects), never
reaching evidence gathering, authorization, or policy evaluation; (2)
**defense-in-depth** — `services/common/sparql_escape.py::escape_sparql_literal`
(backslash/quote/newline escaping per the SPARQL 1.1 grammar) is applied
at both hand-built-SPARQL call sites (`evidence.py`'s ASK,
`rdf_writer.py::record_approval`'s UPDATE) regardless of the upstream
validation. Proven live (not just unit-tested) in
`tests/integration/test_decision_service_injection.py`: a set of hostile
payloads (`'WH-A" } ; DROP ALL ; #'`, `'" || true || "'`, embedded
newlines, an attempted OpenFGA object-string smuggling payload) are all
rejected with zero external WMS effects; the pure-validation proof (no
network) is `tests/contracts/test_decision_service_input_validation.py`.

### Testing strategy: synthetic SKUs, not the canonical fixture

`tests/integration/test_canonical_scenario.py` (Phase 2) already performs
the canonical incident's OWN mitigation via a direct WMS `POST /transfers`
call (bypassing governance by design), which permanently leaves WO-42
MITIGATED (`shortage=0`) for the rest of any stack's lifetime — so Phase 5's
governed-decision tests cannot reuse WO-42/PX-17 as an "at-risk" fixture.
`tests/integration/decision_helpers.py` uses synthetic parts at the REAL
WH-A/WH-B warehouses instead, with one non-obvious wrinkle: a synthetic part
id used directly (e.g. `"PX-TEST-01"`) gets **quarantined** by the identity
resolver (`contracts/identity/v1/mapping_rules.yaml`'s WMS pattern only
recognizes `^SKU-\d{6}$`) and never reaches the hot projection at all — every
helper therefore takes a WMS-local `SKU-9NNNNN` (a range the seed generator
never uses) and derives the CANONICAL id (`sku_to_canonical`) for anything
touching the hot projection or a propose() request.

**Freshness timing**: the 5s `max_evidence_freshness_s` threshold is
tighter than one real CDC round trip (WMS write -> Debezium -> ingestion ->
projection-builder's ~3s poll cycle) can reliably beat, so tests bump a hot
row's `as_of` directly via SQL to `now()` (mirroring
`test_projection_staleness.py`'s opposite-direction technique)
**immediately** before calling `propose()` — any slow operation
in between (a second `set_inventory_and_wait` call, a `docker compose stop`
subprocess) reliably eats the whole window and was caught empirically
during implementation (two tests initially failed with `INSUFFICIENT_EVIDENCE`
instead of their intended outcome until reordered).

**RDF4J SHACL `sh:maxCount` is checked ACROSS THE WHOLE REPOSITORY, not per
transaction-graph** — a second empirical confirmation of the Phase 3
`fac-core-shape.ttl` finding, this time self-inflicted in
`tests/performance/bench_phase5.py`: reusing one fixed
`evidence_snapshot_id` across many separate benchmark decision graphs
accumulated multiple `oo:snapshotObservedAt` triples on that ONE subject
(one per graph it was written into), and the SHACL `sh:maxCount 1` check —
evaluated globally — started 409ing once 2+ such graphs existed. Fixed by
minting a fresh `evidence_snapshot_id` per benchmark iteration too, not just
a fresh `decision_id` (real `propose()` calls always did this correctly;
this was purely a benchmark-script bug).

### Pre-existing Phase 3 bug found and fixed: ingestion consumer crashed on `httpx.RemoteProtocolError`

Running `test_f22_rdf4j_down_fails_proposal_safely` (a real `docker compose
stop/start rdf4j`, same pattern as Phase 3's own
`test_cdc_ingestion.py::test_rdf4j_outage_backs_off_without_data_loss_and_resumes`)
crashed the `services/ingestion` container entirely (`docker compose ps` ->
`Exited (1)`), which then permanently starved every hot-projection-dependent
test downstream (`current_inventory` rows can never converge with nothing
consuming Kafka) until manually restarted — this is what caused several
seemingly-random `INSUFFICIENT_EVIDENCE` failures during implementation
before the real cause was found. Root cause:
`services/ingestion/consumer.py`'s `process_message` only caught
`(httpx.ConnectError, httpx.TimeoutException)` as `RDF4JUnavailable`
(retry-in-place); a mid-request `docker compose stop rdf4j` can instead make
the TCP connection accept and then close before a response is sent, raising
`httpx.RemoteProtocolError` ("Server disconnected without sending a
response") — a THIRD, previously-unhandled transport failure that propagated
uncaught out of the consumer's main loop and killed the process. Fixed by
broadening the except clause to `httpx.TransportError` (the common base of
`ConnectError`, `TimeoutException`, AND `RemoteProtocolError` — verified via
`__mro__`), closing this whole class of transport-level hiccup, not just the
two enumerated by hand in Phase 3. This is a Phase 3 module fixed under
Phase 5 because Phase 5's own dependency-outage tests are what newly
exercise a `docker compose stop rdf4j` mid-request; `make test` was re-run
green 3 consecutive times after the fix (no flakiness).

### Scoping decision: `expedite_purchase_order`/`reschedule_work_order` get lighter test coverage

The brief's explicit negative-test list (F01-F09, F22-F24, F26, F33, plus
08's OPA/OpenFGA lists) is written against `transfer_inventory` — the
canonical action. `expedite_purchase_order` and `reschedule_work_order` are
fully WIRED (propose/evidence/authz/policy/SHACL all real, each with its own
OPA unit tests) and reachable end-to-end, but are not separately exercised
by the full F01-F33 integration matrix — an explicit, documented scope
decision given the time budget, not a gap discovered late.

### `make test` acceptance run (this session)

Exact pytest summary lines, `make test` run 3 consecutive times after the
ingestion fix above, zero flakiness:

```
tests/model: 21 passed
tests/contracts: 55 passed (was 19 before Phase 5)
tests/component: 15 passed
tests/integration: 63 passed (was 36 before Phase 5)
```
(154 total, all three runs identical.)

`make bench`: `hot_read_p95_ms` PASS (phase 4, unchanged), `gate_evaluation_p95_ms`
PASS (~10-17ms measured vs 300ms threshold), `decision_proposal_p95_ms` PASS
(~28-30ms measured vs 500ms threshold). `make reset` verified clean with the
two new services present (openfga/opa healthy with no docker-level
healthcheck, decision_service healthy, bootstrap_openfga.py runs
successfully on a freshly-reset stack).

### What Phase 6 (durable action runtime) needs from here

- `POST /decisions/{id}/execute` already verifies `status == APPROVED` and
  returns the decision's `decision_content_hash` in its 501 body — Phase 6
  only needs to replace the 501 with a real Temporal workflow start, the
  "verify immutable content hash" step is already real.
- `services/decision_service/authz.py::resolve_object` is the pattern for
  binding any FUTURE ActionType to the existing warehouse-scoped
  authorization model without new FGA types — reuse it rather than adding
  `purchase_order`/`work_order` types.
- `wms.transfers` CDC topic (Phase 3) is still unmapped into RDF
  (`services/ingestion/mapping.py` has no `TableSpec` for it) — Phase 6 is
  where that mapping + its semantic meaning (tied to `oo:ActionExecution`,
  whose shape already exists since Phase 3) needs to land.
- `oo:ActionExecution`/`oo:Outcome` RDF population, and the `execution
  identifier`/`observed outcome identifier` H1 fields (currently always
  absent — Decision-shape.ttl does not require them, by design, since they
  don't exist before Phase 6).

## Phase 5 fix — watermark-based evidence freshness

Tag `poc-v0.5-gates` (moved, `git tag -f`, after this fix — see the
"Amendment" note at the end of this section). Reported by an independent
live probe against the running stack, not discovered internally.

### Root cause (with evidence)

`services/decision_service/evidence.py`'s original freshness check fed
`current_inventory.as_of` (the row's own last-CHANGED timestamp, sourced
from `oo:SourcePosition.lastObservedAt`) into `freshness.evaluate()`. That
answers "how long ago did this fact change", not "how recently did we
verify our view is current" — docs/experiment/spec/04_architecture.md's
consistency model explicitly wants the latter (FRESH/STALE describe the
PIPELINE's relationship to the source, not a fact's own age). The practical
consequence, reproduced exactly as reported: `POST /decisions/propose`
{planner-1, transfer_inventory WH-B->WH-A, part PX-17, qty 60} on a
perfectly healthy, fully-caught-up stack returned `INSUFFICIENT_EVIDENCE`,
`missing: ["source_available_fresh"]`, because PX-17's WH-B lot genuinely
had not changed in the last `max_evidence_freshness_s` (5s) — and since
nothing in the canonical incident's steady state ever touches that lot
again after the initial seed, it was STALE FOREVER, on a system with zero
problems. `tests/integration/decision_helpers.py`'s `set_inventory_and_wait`
had been additionally bumping `as_of` to `now()` immediately before every
propose() call specifically to defeat this, which is exactly the "masked it
with a touch-before-propose crutch" the bug report named.

### Design: per-source watermark = min(ingestion's CDC-drain watermark, the hot row's own `computed_at`)

**Ingestion watermark** (`services/ingestion/consumer.py` /
`services/ingestion/health.py`): Debezium's `heartbeat.interval.ms` was
ALREADY configured on every connector since Phase 3
(`contracts/cdc/v1/*-connector.json`, lowered from 5000ms to 1000ms this
fix) but nothing had ever consumed the heartbeat topics it produces —
verified empirically that `__debezium-heartbeat.oo.{erp,mes,wms}` topics
already existed with a fresh `{"ts_ms": ...}` message every interval, even
on a database with zero writes (`kafka-console-consumer` against the live,
idle stack). `run()` now subscribes to `all_topics() + heartbeat_topics()`
together (one consumer, one Kafka group) and calls
`state.touch_watermark(system, now())` on EVERY message for that
system — heartbeat OR real CDC OR poison (a poison message still proves the
CONNECTION is alive; only an `RDF4JUnavailable` retry leaves the watermark
untouched, correctly, since that is the one case where we genuinely cannot
prove we're caught up). Heartbeat topics are deliberately NOT added to
`services/ingestion/readiness.py`'s `CDC_TOPICS` (the `wait_for_zero_kafka_lag`
gate `make wait-converged` depends on) — folding a topic that receives a new
message every second into a "stable zero lag across two 2s samples" check
would make that gate flaky by construction; the two are separate concerns
checked separately (readiness.py gained its OWN `wait_for_ingestion_watermarks`
step instead, see below). Exposed via `GET /health`'s new `watermarks:
{erp, mes, wms}` field (ISO8601 per source).

**Combined pipeline watermark** (`services/decision_service/evidence.py::
_pipeline_verified_through`): `min(ingestion_watermark_for_system,
row["computed_at"])`. `computed_at` (Phase 4, already written by
`services/projection_builder` on every rebuild cycle regardless of whether
data changed) needed no new mechanism — it was already exactly "the
projection builder's own verified_through", just under a different name.
Taking the MORE STALE of the two means either failure mode independently
produces STALE: a paused connector (ingestion watermark stops advancing)
OR a stopped projection_builder (`computed_at` stops advancing) — matching
docs/experiment/spec/09_failure_and_adversarial_matrix.md F26's own
"pause the connector, stop the builder" framing as two equivalent staleness
injections. `_pipeline_verified_through` returns `None` (treated as STALE,
never as an exemption) if ingestion is unreachable or has not yet recorded
a watermark for that system — a real, narrow race at ingestion's own
process startup (empirically observed: ~50s after a fresh `docker compose
start ingestion`, `GET /health` still showed `watermarks: {}` because the
consumer group was mid-rebalance). Closed by adding
`readiness.py::wait_for_ingestion_watermarks` as a new step in
`wait_for_converged()` (between the Kafka-lag check and the RDF4J-fixture
check) — `make up`/`make seed`/`make reset` now block until every source
has a recorded watermark, not just until CDC topic lag is zero.

The watermark is recorded in the evidence snapshot's `source_positions`
list alongside the per-entity positions the action's evidence actually
used, tagged `"kind": "watermark"` (no new RDF property needed — it
serializes into the same `oo:sourcePositionsJson` field
`rdf_writer.py` already writes).

`services/projection_builder/freshness.py::evaluate()` itself is UNCHANGED
— it is a pure "is this timestamp within N seconds of now" function, used
correctly both by Phase 4's OWN per-row staleness concept (still valid for
ITS purpose, e.g. `tests/integration/test_projection_staleness.py`, a
dashboard-style "is this specific fact possibly outdated" question) and now
by evidence.py's pipeline-watermark concept (a governance-decision
"can I trust the pipeline enough to decide" question) — same function,
different INPUT semantics for two legitimately different questions.

### A second, more important bug found validating the fix: outage-recovery tests weren't waiting for genuine reconvergence

`make test` run 3x after the watermark fix above landed was NOT immediately
green — `tests/integration/test_decision_service_approval.py` (and, in one
run, `test_decision_service_canonical.py` too) intermittently failed with
`INSUFFICIENT_EVIDENCE`, always among the FIRST decision-service tests to
run. Root-caused with a continuous background monitor sampling
`current_inventory.max(computed_at)` age and the ingestion `wms` watermark
age every 500ms across a full `make test` run: both sat in a normal 0-3s
sawtooth almost the whole time, but showed THREE separate 11-19 SECOND
stalls, each correlated with a real container stop/start — Phase 3's
pre-existing `test_cdc_ingestion.py::test_rdf4j_outage_backs_off_without_data_loss_and_resumes`,
and this phase's own F22 (RDF4J) and F26 (projection_builder) outage tests.

Each of those tests' `finally` block already waited for the STOPPED
service's bare HTTP health check to respond again before returning — but a
responding health check is NOT the same as `services/ingestion` having
resumed heartbeat processing or `services/projection_builder` having
completed its first post-restart rebuild. Both are INDEPENDENT processes
that also read from/write to the disrupted dependency, so both stall for
several extra seconds AFTER the disrupted service itself reports healthy —
and every one of those three tests returned control to pytest during that
gap, leaking a stale window into whatever test ran next. This is the exact
"looks like flakiness in the NEW code, is actually a pre-existing
insufficient-convergence-check in tests that mutate shared infrastructure"
pattern this repo's Phase 4 fix already named once (docs/experiment/implementation-notes.md's
Phase 4 fix section: "the reported failure had two independent contributing
causes... a false-positive convergence detector").

**Fix**: `services/ingestion/readiness.py` gained
`wait_for_fresh_hot_projection(dsn, max_age_s, timeout_s)` (polls
`max(computed_at)` until it is genuinely recent). Every test that disrupts
RDF4J or `services/projection_builder` now calls it (and, where relevant,
`wait_for_ingestion_watermarks`) in its OWN `finally` block, right after its
bare health-check wait, before returning control to the rest of the suite:
`test_cdc_ingestion.py`'s outage test (Phase 3, fixed under this Phase 5
session since Phase 5's own tests are what surfaced it), and this phase's
F22/F26 (`test_decision_service_dependency_outage.py`). F23/F24 (OpenFGA/OPA)
need no such wait — neither dependency feeds RDF4J or the hot projection.

**`_resolve_source_inventory_with_freshness`'s own retry window
(`services/decision_service/evidence.py`, 10 attempts × 0.8s = 8s) is kept
as defense-in-depth**, not removed now that the root cause is fixed — it
protects against any FUTURE test (or real operational hiccup) that
disrupts the pipeline without yet knowing to wait for full reconvergence,
at the cost of a few seconds of added latency only in that unhappy case.
`make test` was re-run 3 consecutive times after BOTH fixes (watermark
semantics + reconvergence waits) with zero failures, matching the acceptance
run below.

### Test changes

- `tests/integration/decision_helpers.py::set_inventory_and_wait` no
  longer bumps `as_of` — a row set up seconds or minutes before propose()
  is called is now equally FRESH, so the manual bump (which only ever
  worked by racing `services/projection_builder`'s ~3s poll cycle) is
  simply gone. Found and fixed a SEPARATE, unrelated real bug while
  removing it: the helper's `wait_until` polled for "a row exists" rather
  than "a row exists WITH THIS CALL'S OWN VALUES" — harmless as long as
  every test used a never-before-seen SKU (true throughout the original
  Phase 5 suite), but a false-positive the instant a test reused a
  (sku, warehouse) pair a PRIOR run had already converged to a DIFFERENT
  value, which the new quiet-system test below did (SKU-900501, previously
  200, now 140) — caught immediately by its own assertion, fixed by
  matching on-hand/quality_status in the wait predicate, not just row
  presence.
- `propose_with_freshness_retry` (the bump-and-retry crutch this file
  exported) is deleted entirely; every call site now calls propose()
  directly.
- F08's old "push `as_of` back 30s via SQL"
  (`tests/integration/test_decision_service_gates.py`) is replaced by a
  REAL pipeline stall: `test_f26_stalled_projection_builder_yields_insufficient_evidence`
  (`tests/integration/test_decision_service_dependency_outage.py`) stops
  `services/projection_builder`, waits past `max_evidence_freshness_s`, and
  asserts `INSUFFICIENT_EVIDENCE` with zero WMS effects, then restarts it —
  same `docker compose stop/start` pattern as the F22-F24 outage tests it
  now lives alongside.
- NEW: `tests/integration/test_decision_service_canonical.py::
  test_canonical_incident_approves_on_a_quiet_system_no_touch` — the exact
  regression proof. Sets up the canonical incident's own arithmetic (140
  available at WH-B, 60-unit transfer, safety_stock 50 — a
  `contracts/policies/v1/data.json` override for the synthetic
  `PX-800501` maps it to the SAME 50 as the real PX-17@WH-B), sleeps 35 real
  seconds touching NOTHING, then proposes and asserts `APPROVED` with
  `freshness_status: FRESH` and a populated `pipeline_verified_through` —
  and separately asserts the `"kind": "watermark"` entry in
  `source_positions`, proving the freshness verdict traces to the watermark
  mechanism, not to a lucky recent write.

### Acceptance run (this session, after the fix)

```
make test (x3): tests/model 21 passed, tests/contracts 55 passed,
  tests/component 15 passed, tests/integration 64 passed — identical all
  three runs, zero flakiness.
make bench: gate_evaluation_p95_ms and decision_proposal_p95_ms both PASS
  (unaffected by this fix — the watermark fetch is one extra local HTTP
  call to services/ingestion, negligible next to the OpenFGA/OPA/RDF4J
  round trips already being measured).
```

### Amendment note

This fix landed as a SEPARATE commit ("Phase 5 fix: watermark-based
evidence freshness") after the original Phase 5 commit, per the
coordinator's explicit instruction — NOT squashed/amended into the
original. `poc-v0.5-gates` was moved (`git tag -f`) to point at this fix
commit, so the tag always reflects the phase's true final, working state.

### What Phase 6 needs from here (in addition to the section above)

- `services/ingestion/health.py`'s `watermarks` field and
  `services/decision_service/evidence.py::_pipeline_verified_through` (now
  `_resolve_source_inventory_with_freshness`) are the reusable pattern for
  any FUTURE evidence requirement that needs "is the pipeline caught up",
  not "did this fact change recently" — applies equally to
  `expedite_purchase_order`/`reschedule_work_order` if their evidence
  gathering ever grows a freshness requirement of its own (currently it
  does not — they read ERP/MES live via REST, not through the
  hot-projection/CDC path).
- `services/ingestion/readiness.py::wait_for_fresh_hot_projection` is now
  the established convention for ANY FUTURE test that stops/restarts RDF4J
  or `services/projection_builder` — call it (alongside
  `wait_for_ingestion_watermarks` when RDF4J/ingestion was the disrupted
  side) in the test's own `finally` block before returning, exactly like
  `test_cdc_ingestion.py`'s outage test and this phase's F22/F26 now do.
  Skipping this is precisely what caused the 11-19s stale windows this
  fix's own acceptance run found and closed.

## Phase 6 step 0 — protected-transfer authorization

Tag: none yet (part of the upcoming `poc-v0.6-actions` tag). Brief:
`docs/experiment/briefs/phase6.md` item 0 (an orchestrator finding from the
Phase 5 review). Full design + a security-review amendment:
`docs/adr/0003-protected-high-priority-transfer-authorization.md` — read
that first; this section is the shorter operational summary.

### What changed

- `contracts/authorization/v1/model.fga`: new `warehouse` relation
  `can_mitigate_high_priority: planner or supervisor` (junior_planner
  excluded, same split as `can_approve_large_transfer`). No new FGA type —
  bound to the SAME object (`source_warehouse`) `can_transfer_inventory`
  already resolves to.
- `contracts/actions/v1/transfer_inventory.yaml`: new optional, formal
  parameter `work_order` (hash-covered via `decision_content_hash`, unlike
  the pre-existing informational `context.work_order_id`, which is still
  accepted for backward compatibility) plus
  `authorization.protected_relation: can_mitigate_high_priority`.
- `contracts/projections/v1/work_order_risk.yaml` / `services/projection_builder/`
  (compute.py, writer.py, schema.sql, hashing.py): the hot projection now
  carries `fac:priority` (LOW|MEDIUM|HIGH) through unchanged, per-row, with
  its own freshness/provenance — a **security-review-driven addition**, not
  part of the original step-0 design (see below).
- `services/decision_service/evidence.py::_resolve_route_protection`: the
  server-side, non-bypassable determination of whether the PROPOSED
  `(part, source_warehouse, destination_warehouse)` route is itself a real
  `transfer_candidates` row for a fresh, HIGH-priority, at-risk work order —
  entirely independent of whatever `work_order` the caller declared (or
  omitted). `services/projection_builder/reader.py::get_transfer_candidates_for_route`
  is the new query backing it.
- `services/decision_service/authz.py::check_high_priority_protection` +
  `services/decision_service/propose_flow.py`: a second OpenFGA check, run
  only when `evidence.route_protected`, immediately after the base
  `can_transfer_inventory` check ALLOWS. A deny here overwrites
  `record.authz_result` (one authorization verdict per decision, matching
  every other ActionType) and terminates `DENIED_AUTHORIZATION`.
- `services/decision_service/planner.py` (H10): now submits
  `parameters.work_order` for its own canonical recommendation.

### Security review: two gaps fixed before this shipped

An independent review caught the ORIGINAL design (MES-live-call, gated only
on caller-declared `work_order`) failing OPEN on MES-unreachable and being
trivially bypassable by omitting `work_order`. Full root-cause and fix
narrative: ADR 0003's "Security review amendment" section. Summary: priority
now comes from the hot projection (freshness-governed like every other gate
input, never a live decision-service-initiated MES call), and whether
protection applies is derived from the proposed ROUTE server-side, never
from any caller-supplied field. An unresolvable route match is
`INSUFFICIENT_EVIDENCE` for every actor (fail closed), and a caller
declaring a real at-risk work order that the proposed route does not
actually match is also rejected `INSUFFICIENT_EVIDENCE`
(`work_order_route_mismatch`) as an honesty check, not a security gate.

### `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — first migration-style change in this repo

Every prior phase's schema change happened before any stack existed yet, so
`CREATE TABLE IF NOT EXISTS` alone always sufficed. This is the first schema
change against an ALREADY-RUNNING stack (`work_order_risk.priority`) —
`services/projection_builder/schema.sql` now also runs an idempotent
`ALTER TABLE work_order_risk ADD COLUMN IF NOT EXISTS priority TEXT CHECK (...)`
on every startup, nullable so it is safe against existing rows before the
next poll cycle's TRUNCATE+re-INSERT overwrites them (at most one
`OO_PROJECTION_POLL_INTERVAL_S` window). Verified empirically: `make up`
against the ALREADY-RUNNING Phase 5 stack rebuilt `projection_builder`/
`decision_service` images and the column appeared with zero data loss.

### Test verification (this session, live stack)

```
tests/contracts/test_openfga_model.py: 1 passed (fga model test: 9/9 tests, all checks passing)
tests/integration/test_decision_service_protected_transfer.py: 6 passed
tests/integration/test_projection_differential.py + test_projection_consistency.py
  + test_projection_rebuild.py + test_projection_staleness.py: 7 passed
```

Ordinary (non-protected) transfers pay zero extra cost: `_resolve_route_protection`
returns `NOT_APPLICABLE` immediately (no MES-watermark lookup at all) for
every synthetic-SKU test in the existing F01-F09/gates/policy/canonical/
delegation/approval/forensic suites, none of which have any
`transfer_candidates` row — confirmed by the full `make test` run below.

### What Phase 6's remaining steps need from here

- `evidence.EvidenceResult.route_protection_status` /
  `.route_protecting_work_orders` / `.route_protected` are the reusable
  shape for any FUTURE protected-ActionType check that needs "does this
  proposal's route correspond to some other at-risk/critical entity" —
  reuse the pattern (server-derived from the proposal's OWN parameters,
  never from caller-declared context, fail closed on unresolved) rather
  than re-deriving it.
- `work_order_risk.priority` is now available to anything reading the hot
  projection (H13 forensic queries, the deterministic planner, later
  reconciliation logic) without a live MES call.

## Phase 6 — Durable action runtime + CDC reconciliation

Tag `poc-v0.6-actions`. Brief: `docs/experiment/briefs/phase6.md`. Spec: 01
(H3/H4/H5/H12), 03, 05, 06, 08, 09, 11, 14. Step 0 (protected-transfer
authorization) landed as its own prior commit — see that section above and
`docs/adr/0003-protected-high-priority-transfer-authorization.md`; this
section covers steps 1-7.

### Ports

| Service | Host port | Notes |
|---|---|---|
| Temporal frontend (gRPC) | 15473 | `temporalio/auto-setup:latest`, its OWN dedicated Postgres (`temporal-postgres`, no host port) — see "Temporal's own Postgres" below |
| Temporal Web UI | 15474 | optional, human debugging only; nothing in this repo's tests depends on it |
| `services/action_worker` health | 15486 | |
| `services/reconciliation` health | 15487 | |

### Temporal gets its OWN dedicated Postgres, not a database on the shared instance

`db/init/00_init.sh` only runs on the shared Postgres container's FIRST
volume initialization — adding a `temporal` database to it would need a
data-losing `make reset` for every already-running stack (this repo's first
schema change against an ALREADY-RUNNING stack, `work_order_risk.priority`
in step 0, already needed an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
workaround for exactly this reason). A separate `temporal-postgres`
container (plain `postgres:16`, its own named volume
`oo-poc-temporal-pgdata`) needs no such migration and keeps Temporal's
schema fully isolated; `temporalio/auto-setup`'s own entrypoint creates the
`temporal`/`temporal_visibility` databases and runs its schema migrations
itself (`DB=postgres12`, verified via `docker run --entrypoint cat
temporalio/auto-setup:latest /etc/temporal/auto-setup.sh` — the real env
var names, `POSTGRES_SEEDS`/`POSTGRES_USER`/`POSTGRES_PWD`/`DBNAME`/
`VISIBILITY_DBNAME`, were read from the actual script rather than guessed).

### Temporal's healthcheck: `nc -z localhost 7233` fails even when the server is fully up

Empirically found (the first `make up` after adding the `temporal` service
failed with "dependency temporal failed to start: container is unhealthy",
despite the container's own logs showing "Temporal server started" within
~1s): `temporal-server` binds its frontend gRPC port on the CONTAINER'S OWN
bridge-network IP (`172.x.x.x:7233`, confirmed via `docker exec ... netstat
-tlnp`), never on `127.0.0.1` — so a loopback healthcheck can never
succeed, no matter how long it waits. Fixed to `nc -z temporal 7233` (the
container's own compose service hostname, resolvable to that same IP via
Docker's embedded DNS from inside the container itself) — verified
empirically (`docker exec oo-poc-temporal-1 sh -c "nc -z temporal 7233;
echo exit=$?"` → `exit=0`). Real namespace readiness is still proven
separately, from the host, by `services/action_worker/bootstrap_temporal.py`
(same "prove real API readiness from outside a healthcheck" pattern as
`bootstrap_openfga.py`) before `make up` lets anything start a workflow —
it makes a real `list_workflows()` RPC against the `default` namespace, not
just a bare connect.

### `services/action_worker` (the Temporal worker)

Class-based activities (`ActionActivities`, `services/action_worker/activities.py`)
bind `config` (RDF4J/WMS/ERP/MES base URLs) ONCE at Worker-registration
time rather than re-serializing it as a Temporal argument on every activity
call — the standard temporalio pattern for activities that close over
shared config. All three activities are plain SYNCHRONOUS functions (this
repo's established sync-everywhere style), run under a
`ThreadPoolExecutor` via `Worker(activity_executor=...)`.

`ActionExecutionWorkflow` (`services/action_worker/workflows.py`) is
deliberately kept free of any import of `activities.py` (which pulls in
psycopg/httpx/rdflib — Temporal's workflow sandbox forbids non-deterministic
I/O modules in workflow code); activities are referenced by NAME STRING
only, matching the `@activity.defn(name=...)` registration.

Exactly THREE activities per execution, matching spec 06's execute()/
workflow pseudocode:
1. `verify_and_start_execution` — loads the APPROVED decision, verifies it
   is genuinely executable, writes the `oo:ActionExecution` resource and
   flips `oo:status` APPROVED→EXECUTING (`services/common/action_rdf.py::write_execution_started`).
2. `call_external_action` — dispatches to WMS (`transfer_inventory`), ERP
   (`expedite_purchase_order`), or MES (`reschedule_work_order`) with
   `action_execution_id` as the idempotency key. For `transfer_inventory`,
   also snapshots `current_inventory` (source+destination `available`)
   immediately BEFORE the call as the outcome predicate's "before" baseline
   — deliberately NOT the frozen evidence-snapshot value from propose()
   time, since real time may have passed between approval and execution;
   fetching fresh is MORE correct and costs nothing extra.
3. `observe_and_finalize` — for `transfer_inventory`, polls (heartbeating)
   for the CDC-observed `fac:WmsTransferRecord` up to the contract's
   `observation.timeout` (30s), then evaluates the outcome predicate
   (`services/action_worker/outcome_eval.py::evaluate_transfer_outcome`) and
   auto-compensates (`reverse_transfer`) on DIVERGED when
   `compensation.mode: compensatable`. Writes the `oo:Outcome` resource and
   flips `oo:status` to the terminal value
   (`services/common/action_rdf.py::write_execution_finalized`) — the
   SECOND and LAST RDF write per ActionExecution (see that module's own
   docstring for why exactly two, both replay-safe).

`expedite_purchase_order`/`reschedule_work_order` get the documented
LIGHTER treatment Phase 5 already established for these two ActionTypes:
`outcome_eval.evaluate_command_response_outcome` treats ERP/MES's own
synchronous, idempotent command response AS the observation (no CDC poll)
— there is no eventual-consistency story for these two (ERP/MES commit
in-request), so DIVERGED is structurally unreachable for them under this
design; only `OBSERVED_SUCCESS`/`EXECUTION_FAILED`/`OUTCOME_UNKNOWN` occur.

### `wms.transfers` CDC mapping lands here, as Phase 5 predicted

`services/ingestion/mapping.py` now maps `wms.transfers` → `fac:WmsTransferRecord`
(new class, `contracts/ontology/v1/fac-core.ttl`) — the CDC-observed
counterpart to the governance-authored `oo:ActionExecution`, which
`services/action_worker`/`services/reconciliation` correlate an action's
expected effect against (never a live re-query of WMS — H3/H12).
`services/ingestion/consumer.py`'s `TABLES["wms"]` gained `"transfers"`
(it was previously excluded BY NAME specifically to keep
`services/ingestion/readiness.py`'s Kafka-lag check from permanently
"lagging" on a topic nothing consumed) — `all_topics()` is derived from
that dict, so `wait_for_zero_kafka_lag` now correctly covers it too, with
no separate edit needed.

### Bug found and fixed: canonical part id vs. WMS's own local id

First end-to-end smoke test failed: `WMS 404 "no inventory lot for
part=PX-801001 at warehouse=WH-B"` even though the decision had just been
APPROVED against that exact part/warehouse. Root cause: `parameters.part`
is always CANONICAL-id-typed (`contracts/actions/v1/transfer_inventory.yaml`),
but WMS never learns canonical ids at all (services/wms owns no identity-
resolution concept, per the per-system credential/identity isolation
design) — its `inventory_lots.part` column always holds ITS OWN local id
(e.g. `SKU-88429`, never `PX-17`, confirmed against the canonical fixture's
own `source_identity_map`). Fixed by
`services/common/identity_lookup.py::resolve_canonical_part_to_source_local`
(a reverse SPARQL lookup over the SAME `oo:IdentityMapping` records
`services/ingestion/store.py` already writes at CDC ingestion time, scoped
by `oo:sourceSystem`) — `call_external_action` resolves the WMS-local id
immediately before building the WMS request. `expedite_purchase_order`/
`reschedule_work_order` need no equivalent: their ids (`po_id`,
`work_order_id`) are already native/shared across MES/ERP and RDF, unlike
part ids (only columns literally named `part`/`part_id` ever go through
identity resolution — see `services/ingestion/mapping.py`'s own docstring).

### Bug found and fixed: Postgres index row never synced after execute()

Second end-to-end smoke test showed `GET /decisions/{id}` permanently stuck
at `APPROVED` even though RDF4J's own record (and `GET /executions/{id}`/
`GET /outcomes/{id}`) correctly showed the full EXECUTING→OBSERVED_SUCCESS
progression. Root cause: `services/decision_service/store.get_decision`
reads FROM POSTGRES ONLY (spec 06: "the Postgres row is only an index" of
the RDF4J-authoritative record) — Phase 5's `decisions_approve` endpoint
already knew this and called BOTH `rdf_writer.record_approval` AND
`store.update_approval`, but `services/action_worker/activities.py`'s two
RDF writes had no equivalent Postgres sync at all. Fixed by
`services/decision_service/store.py::update_status` (a one-column
`UPDATE ... SET status`), called from both activities (after each of the
two RDF writes) and from `services/reconciliation/reconcile.py`'s own
convergence path. Without this fix, `services/reconciliation`'s own
`watched_decisions()` query (`WHERE status IN ('EXECUTING','OUTCOME_UNKNOWN')`)
would ALSO have silently found nothing, ever — a second, more serious
consequence of the same gap, caught by code review before it shipped
rather than by a second failing test.

### Bug found and fixed: `oo:concernsWorkOrder` never populated via the new `parameters.work_order` path

Writing the H13 query-8 test (below) surfaced that
`services/decision_service/models.py::DecisionRecord.concerns_work_order`
still only read `context.work_order_id` — Phase 6 step 0 moved the
canonical, hash-covered field to `parameters.work_order` but this property
(feeding `rdf_writer.py`'s `oo:concernsWorkOrder` triple) was never updated
to match, so every decision proposed via the NEW field lost its typed
work-order traversal link entirely (silently — propose() itself still
succeeded). Fixed: `parameters.get("work_order") or context.get("work_order_id")`,
same fallback order as `evidence.py` already used.

### Bug found and fixed: a real AB-BA Postgres deadlock between evidence-gathering and projection rebuilds

`_resolve_route_protection`'s original implementation (step 0) made TWO
separate round trips — `transfer_candidates` first, then per-candidate
`work_order_risk` — inside `services/decision_service`'s one long-lived
propose() transaction (`services/common/db.py`: `autocommit=False`, one
connection per request). `services/projection_builder`'s own full-rebuild
transaction TRUNCATEs all four hot tables in a FIXED order
(`work_order_risk` → `transfer_candidates` → `current_inventory` →
`action_eligibility_summary`, `services/projection_builder/builder.py::build_all`).
Whenever a propose() call's route genuinely matched a real candidate (so
BOTH reads actually happened) and overlapped a rebuild cycle, this produced
a textbook AB-BA lock-order cycle — reproduced deterministically (2/2) once
`tests/integration/test_forensic_queries_phase6.py` exercised a REAL
candidate-matching route end to end (every earlier smoke test had used
synthetic parts with `NOT_APPLICABLE` routes, which return before ever
reaching the second read, so the bug was invisible until that test).
Fixed two ways: (1) `services/projection_builder/reader.py::get_transfer_candidates_with_risk_for_route`
replaces the two round trips with ONE JOIN query, so Postgres acquires both
tables' locks as part of a single atomic statement instead of across a
Python-level gap; (2) `services/decision_service/app.py::decisions_propose`
retries up to 3 times on `psycopg.errors.DeadlockDetected` specifically
(Postgres's own self-defense always aborts exactly one side of a detected
cycle; retrying a READ-ONLY evidence-gathering attempt with a fresh
connection is always safe — no write has happened yet) as defense-in-depth,
not the primary fix. Verified with 5 consecutive clean runs of the
triggering test after both fixes landed.

### Bug found and fixed: `MALFORMED QUERY: Invalid escape sequence` from `json.dumps`'s default `\uXXXX` escapes

`services/common/action_rdf.py`'s `write_execution_finalized` 400'd with
"Invalid escape sequence" whenever a JSON blob being embedded contained a
non-ASCII character — reproduced with WMS's own `return_200_without_commit`
fault message (`"...— never persisted"`, a real em-dash). Root cause:
`services/decision_service/hashing.py::canonical_json` (correctly, for ITS
purpose — content-hash stability) uses `json.dumps`'s DEFAULT
`ensure_ascii=True`, which escapes the em-dash to `—` in the JSON TEXT
itself; `escape_sparql_literal` then correctly doubles the backslash to
`\\u2014` for the SPARQL literal — but RDF4J's grammar for a `Modify`
template's (`DELETE {...} INSERT {...} WHERE {...}`) string literals
rejected that sequence, even though an equivalent standalone `INSERT DATA`
statement with the IDENTICAL literal content parsed fine (isolated by
direct reproduction against the live RDF4J container). Fixed by
`services/common/action_rdf.py::json_for_rdf` (`ensure_ascii=False` — the
real UTF-8 character, still escaped for SPARQL-reserved characters by
`escape_sparql_literal`), used for every JSON blob `services/action_worker/activities.py`
writes into RDF; `services/decision_service/hashing.py::canonical_json`
itself is UNCHANGED (hash-critical, not RDF-embedding-critical — two
different concerns that happened to share one function before this fix).

### `services/reconciliation` — the independent re-check (H12), deliberately narrow scope

Only re-drives decisions PostgreSQL shows in `OUTCOME_UNKNOWN` (the
worker's own CDC poll already timed out once) — `EXECUTING` decisions are
COUNTED for visibility but never mutated: Temporal's own durable-execution
replay (not reconciliation) is what resolves a crashed worker's in-flight
EXECUTING decision (F12/F13), and reconciliation mutating a Decision out
from under a workflow that might still be running would race it. On
convergence it uses the EXACT SAME `services/action_worker/outcome_eval.py`
predicate and `services/common/wms_transfer_observation.py` one-shot fetch
the worker itself uses (one definition of "correlated observation", never
two). On DIVERGED it raises a durable `reconciliation_alerts` Postgres row
(`services/reconciliation/schema.sql`, its own index database, same
shared-`ontology_hot` convention as decision_service/projection_builder) —
compensation is deliberately NOT re-attempted from reconciliation itself
(only the ORIGINAL worker's own finalize path compensates), to avoid a
double-compensation race between two independent processes acting on the
same ActionExecution; a reconciliation-detected late divergence is flagged
`MANUAL_RECOVERY_REQUIRED`.

### `tests/faults/` — scope decision (documented, not silently dropped)

The brief lists ~20 fault IDs plus kill tests, network tests, and the
100/80/80 concurrency race. Given the size of this phase, a genuinely
working, directly-verified CORE subset shipped rather than a broader but
shakier attempt at all of them:

- **Implemented, passing**: F10 (duplicate execute() call), F11 (8
  concurrent duplicate execute() calls via threads), F15 (200-without-
  commit → OUTCOME_UNKNOWN, never a fabricated success), F16/F17 (partial
  commit → DIVERGED + auto-compensation reverses the effect exactly), F25
  (real `docker compose stop/start temporal` — approved decision stays
  APPROVED and unexecuted while Temporal is down, then executes normally
  once it recovers), and the 100/80/80 concurrency race (two real decisions,
  concurrent real execute() calls, WMS's own row-locking resolves it: one
  `OBSERVED_SUCCESS`, one `EXECUTION_FAILED`/`DIVERGED`, inventory never
  negative).
- **NOT implemented this phase** (explicit gap, not a silent omission):
  F12/F13 (worker-container kill mid-execution — Temporal's own replay is
  the mechanism under test, not exercised via a real `docker kill` here),
  F18-F21/F35/F38-F40 (CDC delay/duplicate/reorder/poison-message
  injection, clock skew), kill tests for decision_service/projection_builder/
  reconciliation specifically, and network-layer fault injection (latency/
  reset/duplicate delivery via a proxy). `services/reconciliation`'s own
  AWAITING_OBSERVATION→CONVERGED convergence PATH is real and unit-reachable
  (same code F18 would exercise), but nothing in `tests/faults/` currently
  drives it via an actual paused Debezium connector.

### H13 queries 6-8 + `oo:executedBy` (query 5)

`contracts/queries/v1/q6_which_external_objects_changed.rq` (the
ActionExecution's own recorded parameters + command receipt — never
re-derived from current live state), `q7_what_outcome_was_observed.rq`
(the Outcome resource), `q8_which_later_decisions_depended_on_outcome.rq`
(same-work-order causal adjacency via `oo:concernsWorkOrder` + `oo:createdAt`
ordering — documented interpretation, see that query file's own header
comment for the alternative considered and rejected). `q5`'s `executedBy`
binding, deliberately absent through Phase 5, is now populated.
`tests/integration/test_forensic_queries_phase6.py` proves all three plus
spec 03's own acceptance line ("After OBSERVED_SUCCESS, the canonical
incident's work_order_risk projection changes from critical to mitigated")
against a REAL at-risk work order discovered live in the seeded dataset —
same non-hard-coded-WO-42 rationale as the step-0 protected-transfer test.

### `make test` acceptance run (this session)

```
tests/model: 21 passed
tests/contracts: 61 passed (was 55 before Phase 6 — 3 new action-execution-shape
  fixtures + 3 new oo:OutcomeShape fixtures)
tests/component: 15 passed
tests/integration: 71 passed (was 70 after step 0 — +1, test_forensic_queries_phase6.py)
```
`make test-faults` (never part of `make test` — real `docker compose stop/
start temporal`, same "run alone" rule as `make test-destructive`): 6
passed in 67.93s. `make bench` (phase4+phase5+phase6): SLOs unaffected
(hot_read/gate_evaluation/decision_proposal all still PASS); Phase 6's own
three stages (external_action_duration_ms, cdc_observation_lag_ms,
end_to_end_execution_ms) have no locked SLO — see
`experiments/exp-000/results/bench-phase6.json` for the measured numbers
from this run.

### What Phase 7 (contract versioning / replay) needs from here

- `oo:ActionExecution`/`oo:Outcome` are now real, populated resources per
  executed decision, living in the SAME per-decision named graph as the
  Decision itself (`services/common/rdf_graphs.py::decision_graph_iri`) —
  replay's "exact evidence hash recovery" and "same original gate results"
  requirements extend naturally to these without a new graph-naming scheme.
- `services/common/decision_status.py::status_concept_iri` and
  `services/common/action_rdf.py`'s replay-safe DELETE/INSERT pattern are
  the reusable primitives for any FUTURE Decision-lifecycle mutation —
  reuse them rather than hand-rolling a new SPARQL UPDATE string builder.
- The Postgres-index-must-be-explicitly-synced lesson (two bugs above) is
  now a general rule for this codebase: ANY code that mutates a Decision's
  RDF status must ALSO call `store.update_status` in the same breath —
  there is no automatic sync mechanism, and `GET /decisions/{id}` will
  silently go stale otherwise.
- `contracts/manifests/current.json`'s per-action `sha256` (F34: "action
  definition changes post-approval → approved pinned version executes or
  decision invalidated explicitly") is REFERENCED but not yet actively
  VERIFIED at execute() time — `verify_and_start_execution` re-checks the
  decision's own immutable content hash and status, but does not re-hash
  `contracts/actions/v1/<name>.yaml` against what was pinned at propose()
  time and compare. Phase 7's replay work should close this gap as part of
  its own version-pinning verification, not leave it as a second silent gap.
  **Closed in Phase 6b** — see that section below.

## Phase 6b — Complete the fault matrix

Tag `poc-v0.6.1-faults`. Brief: `docs/experiment/briefs/phase6b.md`. Spec:
06, 09 (whole matrix), 11; implementation-notes.md Phase 6 section's own
"tests/faults/ — scope decision" subsection (the explicit gap list this
phase closes). Result artifact:
`experiments/exp-000/results/fault-matrix-phase6b.json` — every F01-F40
with status, owning phase, and real test node id(s), generated by a script
that verifies every id against a live `pytest --collect-only` run rather
than hand-typed-and-trusted. **35 PASS, 5 NOT_TESTED** (F28/F29 need Phase
7's replay/versioning machinery; F30 needs the Phase 9 agent/MCP layer;
F39 needs Phase 7 contract-compatibility fixtures; F40 needs the Phase 10
observability layer — all five explicitly named as out of scope by this
phase's own brief).

### F34 — action-definition version pinning, implemented (not just tested)

Phase 6 left this as a documented gap (see above). Closed by:
`services/decision_service/propose_flow.py` now stamps
`record.action_pinned_sha256` from `contracts/manifests/current.json`'s
per-action sha256 (the SAME manifest `content_addressed()` already uses for
ontology/shapes/authorization/policy versions) onto every Decision —
`services/decision_service/schema.sql` gained an `action_pinned_sha256`
column (both in the `CREATE TABLE` for a fresh reset and an `ALTER TABLE
... ADD COLUMN IF NOT EXISTS` for the already-running stack, same pattern
as `work_order_risk.priority` in Phase 6 step 0), and
`services/decision_service/rdf_writer.py` writes it as `oo:actionPinnedSha256`.
`services/action_worker/activities.py::verify_and_start_execution` now
re-hashes `contracts/actions/v1/<name>.yaml` FRESH off disk (never via
`services/decision_service/action_types.py::get_action_type`'s cached
`_REGISTRY`, which would never observe a post-startup file change) and
compares against the pinned value — a mismatch writes a NEW
`oo:ActionVersionInvalidated` status (added to `contracts/ontology/v1/oo-core.ttl`'s
`oo:DecisionStatusScheme` and `contracts/shapes/v1/decision-shape.ttl`'s
`sh:in` enumeration) via `services/common/action_rdf.py::write_action_version_invalidated`
and raises a non-retryable `ApplicationError` — the external system is
NEVER called once a mismatch is detected.

`tests/faults/test_action_version_pinning.py` exercises this live: mutates
`contracts/actions/v1/transfer_inventory.yaml` on disk (appends a comment,
changing its sha256) AFTER a real decision is APPROVED, then calls
execute(). This needed one infrastructure change:
`docker-compose.yml`'s `action_worker` service gained a read-only bind
mount `./contracts:/app/contracts:ro` — the Dockerfile's `COPY contracts`
is a build-time snapshot, so without a bind mount the running container
could never observe a post-approval host-side edit at all. Found
empirically while building the test: Docker Desktop's bind-mount file
sharing (virtiofs/osxfs on this machine) has a short (~1-2s) propagation
delay between a host write and that write becoming visible via a
container's own read — a `time.sleep(2.0)` settle after the mutation,
before triggering execute(), was needed for the test to be reliable.

### F12/F13 — worker crash, via a real `docker compose kill`

`services/common/test_hooks.py` (new): a Postgres-backed cross-process
pause-point registry (`test_action_worker_hooks` table in `ontology_hot`,
only applied when `OO_TEST_MODE=1`) — needed because the TEST process
(which issues the real `docker kill`) and the paused Temporal activity run
in DIFFERENT containers, unlike `services/wms`'s own in-memory
`FaultRegistry` (`services/common/faults.py`), which only ever needs
same-process coordination. A test arms `(action_execution_id, checkpoint)`
via a direct Postgres write before calling execute(); `maybe_pause()` is
called at the top of `call_external_action` (checkpoint `"pre_call"`, F12)
and `observe_and_finalize` (checkpoint `"post_call_pre_record"`, F13) —
no-op unless armed, near-zero overhead for every other test.

**Bug found and fixed while building this**: the pause must be consumed on
FIRST reach (`WHERE ... AND reached_at IS NULL` in the query), never
re-armed automatically. The first version re-paused on every Temporal
retry too — and since F12's `pause_seconds` (25s, enough for the test to
detect the checkpoint and issue a real `docker kill`) exceeded
`call_external_action`'s own `start_to_close_timeout` (20s,
`services/action_worker/workflows.py`), EVERY retry attempt hit the SAME
pause and got killed by its own timeout before ever reaching the real WMS
call — an infinite non-progressing retry loop, decision stuck at
`EXECUTING` forever, never converging. Fixed, then verified F12/F13 pass
together with the rest of `tests/faults/` repeatedly.

F13's checkpoint reuses `observe_and_finalize`'s EXISTING
`heartbeat_timeout` (10s, already there for `_poll_wms_transfer_record`'s
own CDC-observation wait) — no new Temporal option needed. F12's
checkpoint deliberately does NOT get a `heartbeat_timeout` added to
`CALL_EXTERNAL`: F14's `commit_then_timeout` fault legitimately blocks
`call_external_action`'s own httpx call for ~12s with zero heartbeats in
between (a normal, unpaused execution), and adding a short
`heartbeat_timeout` there risked Temporal treating that as a stalled
activity and dispatching a SPURIOUS retry mid-flight, racing the real one.
F12 instead relies on the existing 20s `start_to_close_timeout` alone to
detect the killed worker — slower (~20-25s to converge) but never
introduces a new false-retry risk on the unrelated F14 path.

### F14 — commit-then-timeout, end to end

`services/wms/transfers.py`'s `commit_then_timeout` fault mode already
existed (Phase 6) and was already proven at the WMS layer alone
(`tests/integration/test_wms_faults.py`). `tests/faults/test_commit_then_timeout.py`
arms it with `timeout_s=12.0` — deliberately ABOVE
`services/action_worker/activities.py::call_external_action`'s hardcoded
10s httpx client timeout, so the WORKER's own HTTP call genuinely times
out client-side even though WMS already committed server-side. Temporal's
`CALL_EXTERNAL` retry policy (`maximum_attempts=5`) retries the SAME
activity, which re-POSTs the SAME `action_execution_id`/body — WMS's own
`body_hash`-matched idempotent replay resolves it to the one already-
committed effect, never a second one.

### F18/F21 — CDC delay and Kafka outage, via the real Kafka Connect REST API

F18 pauses/resumes the real `oo-poc-wms-connector` via
`PUT {connect_url}/connectors/{name}/pause` / `.../resume` (the classic
Kafka Connect REST endpoints, still supported by this stack's Debezium
2.7/Connect image) — WMS still commits the transfer for real (the fault is
purely in the OBSERVATION path), so the worker's own 30s CDC-observation
poll times out → `OUTCOME_UNKNOWN` / `oo:Outcome.reconciliationState =
AWAITING_OBSERVATION`. Resuming the connector lets the delayed CDC event
land; `services/reconciliation`'s own independent poll loop (H12 — the
ONLY thing that ever mutates an `OUTCOME_UNKNOWN` decision, per Phase 6's
own documented scope) converges it to `OBSERVED_SUCCESS` with zero further
test intervention. **Found flaky empirically**: Kafka Connect's pause REST
call returns before the connector's task actually stops consuming (it's
async) — without a short settle (`time.sleep(2.0)`) after pausing, execute()
could race a still-draining task and let the transfer's CDC event through
before the pause genuinely took effect. Same fix applied in both
`tests/faults/test_cdc_delay_and_kafka_outage.py::test_f18_...` and
`tests/faults/test_kill_restart_convergence.py`'s own connector-pause use.

F21 stops the whole `kafka` container (`docker compose stop kafka`) —
same watermark-staleness pattern as Phase 5's F26 test (stalled
`projection_builder`), except the source of staleness is the whole CDC
transport. **This surfaced a real, previously-hidden concurrency bug**, not
just a flaky test: `services/decision_service/evidence.py::_resolve_source_inventory_with_freshness`'s
up-to-8s staleness-retry loop (`_FRESHNESS_RETRY_ATTEMPTS=10`,
`_FRESHNESS_RETRY_DELAY_S=0.8`) ran entirely on the SAME Postgres
transaction/connection `propose()`'s caller passed in
(`services/decision_service/app.py`'s one `with get_conn() as conn:` per
request, `autocommit=False`) — meaning it held its `current_inventory` read's
`AccessShareLock` open for the WHOLE retry window instead of releasing it
between polls. Under a SUSTAINED outage (Kafka down for an entire propose()
call, not just one poll gap — exactly F21), that turned the
ALREADY-DOCUMENTED, previously-rare Phase 6 AB-BA deadlock against
`services/projection_builder`'s TRUNCATE order ("verified with 5
consecutive clean runs" in the Phase 6 section above) into a NEAR-CERTAIN
one — reproduced 10/10 in isolation (every attempt hit "deadlock retries
exhausted" even with random-jittered retries). Fixed by committing between
retry attempts inside that function (it is read-only; `propose()`'s first
WRITE is `store.insert_decision`'s own commit, much later in the same
request) — verified against both this phase's new F21 test and Phase 5's
existing F22/F23/F24/F26 dependency-outage suite (unaffected, still green).

### F19/F20/F35 — CDC dedup/reorder/clock-skew, component-level

All three drive `services.ingestion.store.IngestionStore.apply_event`
DIRECTLY against the real running RDF4J repository — the exact same
function `services/ingestion/consumer.py::process_message` calls per real
Debezium message — rather than fabricating raw Kafka/Debezium byte
envelopes (a deliberate, documented choice: the envelope format is
Debezium's own implementation detail, not part of the idempotency/ordering
contract under test, and this is deterministic where a real Kafka delivery
race would not be). F19 already had equivalent coverage at
`tests/integration/test_cdc_ingestion.py::test_duplicate_cdc_event_is_idempotent`
(Phase 3) — mirrored here so it also runs under `make test-faults` per this
phase's own brief. F35 has no wall-clock INPUT to even inject skew into
(`services/ingestion/lsn.py`'s `ordering_key` takes only `source_lsn`/
`source_version`) — its test proves that property directly (a pure unit
test) plus an end-to-end version through `apply_event` framed explicitly
around clock skew, per the brief's own "or document why F20 covers it and
add a unit test" option.

### F36/F37/F38 — concurrent receipt, manual DB edit, poison message

F36 (`tests/faults/test_concurrent_stock_receipt.py`) writes an unrelated
stock receipt directly via WMS's `_test/inventory/set` endpoint WHILE a
governed transfer is in flight on the SAME (part, warehouse) lot, proving
`services/action_worker/outcome_eval.py::evaluate_transfer_outcome`'s
correlated-record design (spec 06: "must use correlated transaction/
transfer facts rather than naive absolute arithmetic") actually matters —
the decision's own outcome stays correct regardless.

F37 (`tests/faults/test_manual_db_edit.py`) connects DIRECTLY to WMS's own
Postgres (bypassing the WMS HTTP API entirely — no `action_execution_id`,
no test-mode fault registry) and UPDATEs an `inventory_lots` row by raw
SQL. The change still flows through the real CDC pipeline (Debezium reads
the WAL directly, with no concept of "via the API" vs. "via psql") and
becomes an observed fact WITH real provenance, but is structurally
unattributable to any action — no `transfers` row (the ONLY table an
ActionExecution's effect is ever correlated through) ever existed for it.

F38 (`tests/faults/test_poison_message.py`) produces a genuinely malformed
message (invalid JSON) directly onto a real CDC topic via `confluent_kafka.Producer`
(`seed/db_env.py` gained `kafka_bootstrap_servers()`) and drives
`services/ingestion/consumer.py`'s real DLQ path end to end: the
`poison_messages` health counter increments, a real record lands on
`oo.ingestion.dlq` (consumed back and matched by a unique marker, never
trusting "some poison message or other arrived"), and a normal WMS write
made afterward still converges — the pipeline never wedges on one bad
message. This mechanism itself shipped in Phase 3
(`services/ingestion/consumer.py::send_to_dlq`); this phase adds its first
live end-to-end test.

**F36 also exposed a second real bug**, independent of the F21 one above:
`services/ingestion/store.py::_update_position` and `_write_identity_record`
each did `RDF4JClient.delete_subject()` then `add_turtle()` as TWO
SEPARATE HTTP calls/RDF4J transactions — a real window where the subject's
triples were ABSENT from the graph between the two. Both are re-asserted
on EVERY CDC event that touches their row AT ALL, even one that leaves the
mapped value unchanged (an unrelated `on_hand` update still carries `part`
in Debezium's `after` image) — so under concurrent load (F36's own
deliberately-racing write) a reverse `oo:IdentityMapping` lookup
(`services/common/identity_lookup.py`, called mid-execution by
`call_external_action`) could momentarily observe "no mapping" for a part
that has a real, unchanged mapping both immediately before and after,
surfacing as `"no WMS identity mapping found for canonical part ..."` — a
NON-retryable `ApplicationError` that permanently failed the workflow.
Fixed by `IngestionStore._replace_subject_atomic`: one SPARQL Update
(`DELETE WHERE {...} ; INSERT DATA {...}`) per rewrite instead of two HTTP
calls, the SAME one-POST-one-transaction pattern already established
elsewhere in this codebase (`services/common/action_rdf.py`,
`services/decision_service/rdf_writer.py::record_approval`). Both bugs
were caught by running `make test-faults` TWICE back-to-back, per this
phase's own instruction — the first run doesn't reliably reproduce either
race; the second does.

### Kill tests + network faults

`tests/faults/test_kill_restart_convergence.py` covers the three
non-Temporal-worker components the matrix's kill-test section names
(F12/F13 already cover `action_worker` separately): `decision_service`
(stateless — a mid-flight request fails honestly with a real connection
error, a fresh request after restart succeeds normally, no reseed/
rebootstrap step), `projection_builder` (a WMS write made while it's down
still converges once restarted, no manual rebuild), `reconciliation` (a
decision parked in `OUTCOME_UNKNOWN` via a paused WMS connector still
converges once reconciliation itself is killed, restarted, and the
connector resumed — proving its own poll loop recovers with no
special-cased restart handling).

`tests/faults/test_network_faults.py`: deterministic WMS fault-registry
test doubles (documented decision over standing up a toxiproxy container —
the brief explicitly allows either) for latency (`delay_commit`, one
effect despite the delay) and connection failure
(`return_500_before_commit`, the closest same-layer analogue a fake WMS
can produce to a severed TCP connection — zero effect, never fabricated).
Timeout and duplicate-HTTP-delivery are already covered end to end by the
F14 and F10/F11 tests respectively, cited rather than duplicated.

### Security fix found via review: SPARQL/IRI injection in every data-derived IRI builder

A security review of this phase's own commits (specifically the new
`IngestionStore._replace_subject_atomic` above) found that entity/graph
IRIs built from EXTERNAL/DATABASE-sourced data — a WMS/ERP/MES primary key
or column value read back via CDC, a plain `TEXT` column with no charset
constraint at the schema level — were embedded via plain Python f-string
interpolation into raw SPARQL query/update strings with NO IRIREF-safe
escaping, throughout `services/ingestion/mapping.py`, `services/ingestion/store.py`,
`services/common/rdf_graphs.py`, and (via those shared builders)
transitively `services/common/action_rdf.py`/`services/decision_service/rdf_writer.py`.
`services/common/sparql_escape.py`'s existing `escape_sparql_literal`
defends a DIFFERENT SPARQL grammar production (a quoted string literal,
`"..."`) and covers none of IRIREF's forbidden characters
(`<>"{}|^`\` plus control chars 0x00-0x20) — several call sites
(`services/common/identity_lookup.py`, `services/common/action_rdf.py`,
`services/decision_service/rdf_writer.py`) were even using the literal
escaper FOR an IRI component, which neither breaks nor protects that
position. F37 (a direct manual DB edit) and F38 (a poison CDC row) are
exactly the adversarial inputs this closes: a crafted WMS `lot_id`/ERP
supplier id containing `>`, `}`, `"`, whitespace, or control characters
could otherwise break out of an IRIREF and inject arbitrary SPARQL (e.g.
`; DROP ALL ; #`) into a hand-built query.

Fixed by `services/common/iri.py` (new): `safe_iri_component` percent-encodes
a single data-derived path component (a no-op for the overwhelming common
case — ids matching `^[A-Za-z0-9_-]+$`, which is every id this codebase's
own generators/fixtures ever produce, encode byte-for-byte identical to
their input); `assert_safe_iri` is defense-in-depth on a fully-assembled
IRI immediately before the actual raw f-string interpolation. Applied
inside every SHARED IRI-builder this codebase already centralizes IRI
construction through (`fac_instance_iri`/`oo_instance_iri`/
`decision_graph_iri` in `rdf_graphs.py`; `entity_iri`/`part_iri` in
`mapping.py`; `position_iri`/`identity_mapping_iri`/`quarantine_iri` in
`store.py`), so every caller is protected automatically without needing to
remember to sanitize individually — the same "one place so every writer/
reader agrees" design `rdf_graphs.py` already documented for a different
reason (Phase 3) turned out to be exactly the right shape for this fix
too. The three wrong-escaper-for-IRI-context call sites were also cleaned
up to stop pre-processing with `escape_sparql_literal` (now redundant —
the shared builders handle it — and misleading, since a future reader
could mistake it for the actual protection).

Verified LIVE against the real running stack (not just unit-level):
rebuilt `ingestion`/`decision_service`/`action_worker`/`reconciliation`,
waited for full pipeline reconvergence, then inserted a WMS `warehouses`
row with `warehouse_id = 'X> } } ; DROP ALL ; #'` and another with an
embedded newline/CR/tab, plus a malicious `inventory_lots` row, all
directly via SQL (no WMS API, matching F37's own attack shape). Result:
RDF4J's triple count only grew (256021 → 256086, zero data loss), the
canonical WO-42 fixture stayed present (no injected `DROP ALL` ever
executed), `ingestion`'s consumer stayed healthy throughout with 0 poison
messages, and both malicious ids landed as correctly percent-encoded IRIs
(confirmed via a direct SPARQL query: `Warehouse/X%3E%20%7D%20%7D%20%3B%20DROP%20ALL%20%3B%20%23`
and `Warehouse/Y%0Aline2%0D%09tab`). Cleaned up the test rows afterward;
re-ran the full `tests/faults/` suite clean.

### A second pre-existing state issue found and fixed: canonical fixture drift

The final `make test` run failed
`tests/integration/test_canonical_scenario.py::test_step4_transfer_60_units_wh_b_to_wh_a`
— `LOT-A-PX17.on_hand` was 90, not the expected 80 (and `LOT-B-PX17` was
70, not 80). Investigated before touching anything: the canonical
transfer's OWN WMS record (`ae-canonical-transfer-60`) was verified intact
and correct (`requested_quantity=60, actual_quantity=60, status=COMMITTED`,
timestamped hours before this phase's session began) — the discrepancy was
an UNRELATED, EXTRA 10-unit movement on the SAME two lots, both updated at
the identical microsecond timestamp (`05:30:09.389105`), well before any
of this phase's own tests ran (which, per the established convention
documented in `tests/integration/decision_helpers.py`, only ever use
SYNTHETIC non-canonical SKUs — grepped to confirm none of this phase's new
tests reference `SKU-88429`/`PX-17` at all). This is residual drift left
by the PRIOR Phase 6 implementation session's own manual smoke-testing
against the real canonical fixture (that session's own notes describe
exactly this kind of live verification), not a Phase 6b regression.
Corrected directly via SQL (`UPDATE inventory_lots SET on_hand = 80 WHERE
lot_id IN ('LOT-A-PX17', 'LOT-B-PX17')`) rather than a full `make reset`
(the transfer history itself was never in question, only two derived
on-hand values); `make test` is clean afterward.

### `make test-faults` acceptance (twice back-to-back, per this phase's own instruction)

```
Run 1: 24 passed in 268.61s
Run 2: 24 passed in 262.45s
```

### `make test` acceptance (this session, after the canonical-fixture correction above)

```
tests/model: 21 passed
tests/contracts: 61 passed
tests/component: 15 passed
tests/integration: 71 passed
```

### What Phase 7 needs from here

- F28/F29/F39 (ontology migration incompatibility, old-policy-deleted
  replay, invalid mapping-rule deployment) all need the contract-
  versioning/replay machinery this phase deliberately left untouched
  (`POST /replay/{decision_id}` is still the Phase 5 501 stub).
- `oo:actionPinnedSha256`/`oo:actionSha256AtExecute`/
  `oo:actionVersionInvalidatedAt` (F34, this phase) are the first
  contract-version-pinning fields actually VERIFIED at runtime, not just
  referenced — Phase 7's replay work should extend the SAME pattern
  (pin-at-propose, verify-fresh-at-use) to ontology/shapes/policy/
  authorization versions rather than inventing a second mechanism.
- `services/common/iri.py` is now the required helper for ANY new code
  that builds an IRI from external/database-sourced data — Phase 7's
  contract-version fixtures and Phase 9's agent/MCP layer (F30, F39) will
  both introduce new data-derived identifiers and must route them through
  it from the start, not retrofit it later the way this phase had to.

## Phase 7 — Contract versioning, migration, historical replay

Tag `poc-v0.7-replay`. Brief: `docs/experiment/briefs/phase7.md`. Spec: 01
(H7, H8, H13), 07 (whole), 08 (replay tests), 09 (F28, F29, F39), 11
(criterion B), 14 (R4, R6, R10). No new ports — reuses OPA (15482),
OpenFGA (15481), RDF4J (15480-range), decision_service (15410), Postgres
(15432) from earlier phases.

### The core mechanism: a per-kind, live-editable version pointer

`contracts/manifests/deployed_version.json` — one JSON object, one key per
contract kind (`ontology`, `shapes`, `actions`, `policies`, `authorization`,
`identity`, `projections`, `reconciliation`), each holding which
`contracts/<kind>/vN/` directory is CURRENTLY live. `services/common/contract_versions.py::deployed_version()`
reads it fresh off disk on **every** call — never cached in-process, the
same "never trust a stale cache across a store wipe" policy
`services/decision_service/app.py::_current_store_id` already established
for OpenFGA. Every kind advances **independently**: this experiment's
actions/ reached v3 while ontology/shapes/policies/projections stopped at
v2 and authorization only reached v2 with a totally different meaning (its
OWN second version, not "the v3 era") — see the "V3" section below for why
that's correct, not a bug.

"Deploying" a new version is therefore a **data-only edit to one file**,
picked up by the next request with **no container restart** for anything
that reads it per-request (`services/decision_service/app.py::_deps`
rebuilds the manifest fresh every propose() call;
`services/projection_builder/definitions.py::definitions_dir()` re-resolves
on every projection load). `docker-compose.yml` changes made this possible:
`decision_service` and `projection_builder` both gained the SAME read-only
`./contracts:/app/contracts:ro` bind mount `action_worker` already had from
Phase 6b's F34 work; `opa`'s mount widened from `./contracts/policies/v1`
to the WHOLE `./contracts/policies` tree, so `--watch` picks up a brand-new
version's `.rego` (a distinct package name, e.g.
`factory.inventory.transfer_v2` vs v1's `factory.inventory.transfer`) with
**zero** restart, and both packages stay simultaneously servable forever —
which turned out to be exactly what replay needs (see below).

### V1 -> V2: ontology + policy + action evolution

`contracts/ontology/v2/fac-core.ttl` retires `fac:availableQuantity`
(V1's `onHand - reserved` derived convenience property — `onHand`/`reserved`
were ALREADY the real facts since Phase 3, so this needed no new source
columns, only retiring the derived one). `contracts/policies/v2/transfer_inventory.rego`
(package `factory.inventory.transfer_v2`) reads onHand/reserved directly,
adds a NEW `reservation_ok` (reserved <= on_hand) hard-deny rule, and reads
a genuinely different (higher) safety-stock default from
`contracts/policies/v2/data.json`'s `safety_stock_v2` block.
`contracts/actions/v2/transfer_inventory.yaml` (version 2) makes
`reservation_ok` a new required-evidence/closure field and LOWERS
`approval_threshold_units` from V1's 100 to 80 — a deliberate, genuine
behavior divergence used later to demonstrate the counterfactual path.

`migrations/v1_to_v2/migrate_rdf.py` does the one real state migration this
step needs: a SPARQL `DELETE WHERE` removing every live `fac:availableQuantity`
triple from the CURRENT observed graph (never touches any per-decision
historical graph — those are immutable by construction).
`migrations/v1_to_v2/deploy.py` orchestrates: migrate, flip
`deployed_version.json`'s ontology/shapes/actions/policies/projections
pointers to v2, force an immediate projection rebuild with a
before/after hash proof.

**Found via that rebuild's own hash-mismatch check, not assumed**: deleting
`fac:availableQuantity` ALSO broke `contracts/projections/v1/work_order_risk.yaml`'s
`inventory_available` query, which required the same triple as a hard
(non-`OPTIONAL`) graph-pattern element — every `work_order_risk` row
silently lost its `available` figure, recomputing shortage/at_risk wrong.
Both `contracts/projections/v2/current_inventory.yaml` and
`contracts/projections/v2/work_order_risk.yaml` fix this the same way:
`OPTIONAL { ?lot fac:availableQuantity ?rawAvailable }` +
`BIND(COALESCE(?rawAvailable, (?onHand - ?reserved)) AS ?available)` —
works identically whether the triple still physically exists or not.
Verified live against the real running stack: 2,290 `fac:availableQuantity`
triples migrated, all four projection tables' rebuilt hash matched their
pre-rebuild hash exactly.

`services/decision_service/evidence.py`/`policy.py` are now version-aware:
`gather_transfer_inventory_evidence` branches on `action.version_dir` for
the safety-stock lookup and the new `reservation_ok` fact;
`policy.py::build_input` has a V1 and a V2+ input-shape branch. **Found and
fixed live**: `_load_safety_stock` was originally keyed off
`action.version_dir` (the ACTIONS directory) rather than
`action.policy_package` — broke the instant V3 deployed (`contracts/actions/v3/`
exists, `contracts/policies/v3/` never does, since V3 doesn't touch
policy at all) with a live 500 looking for a `data.json` that was never
meant to exist. Different contract kinds evolve on independent clocks;
never assume one kind's version number implies another's.

### V2 -> V3: authorization-model evolution (the "second incompatible evolution")

Deliberately a DIFFERENT KIND of breaking change than V1->V2's — see
`docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md`.
`contracts/authorization/v2/model.fga` adds a `senior_approver` relation and
`can_approve_large_transfer_v2`, NOT unioned with plain `supervisor` — a v1
supervisor tuple alone no longer grants v2 approval authority.
`contracts/actions/v3/transfer_inventory.yaml` (version 3) is the one
resulting action-schema delta: `approval_relation` moves to
`can_approve_large_transfer_v2` (everything else byte-identical to v2's
file). `migrations/v2_to_v3/migrate_authz.py` publishes the v2 model as a
BRAND NEW model in the SAME live OpenFGA store (`services/decision_service/bootstrap_openfga.py::bootstrap`
generalized to take an `auth_dir` param — OpenFGA models are immutable-by-id
and additive, so v1's model is never touched, edited, or deleted) and
migrates `supervisor-1`'s authority forward
(`contracts/authorization/v2/tuples.yaml`'s one new tuple) — the real F28
case a skipped migration would silently regress.
`migrations/v2_to_v3/deploy.py` flips `deployed_version.json`'s `actions`
to `v3` and `authorization` to `v2` (its OWN second version — NOT "v3";
per-kind independent numbering, see above).

Every `Decision`/`AuthorizationCheck` now pins the REAL OpenFGA
`authorization_model_id` (`oo:openfgaAuthorizationModelId`,
`oo:checkAuthorizationModelId` — new optional properties, distinct from the
existing content-hash `authorizationModelVersion`), resolved fresh per
request via `authz.py::resolve_latest_authorization_model_id`
(`GET /authorization-models?page_size=1`, newest first). Live-verified end
to end: a V3 decision (quantity 90, `REQUIRES_APPROVAL`) approved
successfully by `supervisor-1` (the migrated principal) via
`can_approve_large_transfer_v2`, executed to `OBSERVED_SUCCESS`.

**A real infrastructure event, observed and recovered, not hidden**:
partway through this phase OpenFGA's `memory` datastore lost its v2 model
(container restarted with `RestartCount=0`, i.e. a recreation, not a crash
— exact trigger not conclusively identified; root-causing further wasn't
worth the time against everything else left to build). Recovered by
re-running `bootstrap_openfga.py` then `migrate_authz.py`. This is the
EXACT risk `docs/adr/0004` documents as this design's one real gap
(`memory` engine, no persistent OpenFGA storage in this POC) — every
corpus decision's authorization replay therefore reports
`authz_replay_mode: "recorded_only"` rather than `"live"` (their ORIGINAL
model ids no longer resolve in the post-recovery store), which is the
documented, honest fallback working exactly as designed, not a silent
false pass.

### Full per-decision contract pinning (spec 07 item 1's "verify; fix Phase 5 if not")

Closed the gap: every Decision now also pins `identityMappingVersion`,
`projectionDefinitionVersion`, `reconciliationPredicateVersion` (new
optional `oo:` properties, `sh:maxCount 1` with no `sh:minCount` so every
pre-Phase-7 decision keeps validating unchanged), plus `actionVersionDir`
(WHICH `contracts/actions/<dir>/` a decision's `actionPinnedSha256` was
computed from — F34's re-verification needed this once actions stopped
being globally "v1"; threaded through `services/action_worker/activities.py`
and the `/approve` endpoint, new `action_version_dir` Postgres column via
the same `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern Phase 6b
established). `contracts/reconciliation/v1/predicates.yaml` is a new,
versioned, content-hashable DESCRIPTION of `services/action_worker/outcome_eval.py`'s
existing predicate logic — honestly scoped as description-only (not yet
dynamically loaded/interpreted; changing the real predicate still needs a
code change, versioned via `code_git_commit` like any other code change),
documented in the file itself rather than silently implied otherwise.

### Historical corpus — LIVE tier (spec: ">= 100 V1 + >= 100 V2, real
executions for >= 200 complete chains, denied/failed/diverged/unknown via
fault injection")

`seed/generators/historical_corpus.py` (+ `corpus_helpers.py`) drives the
REAL decision service — propose -> approve -> execute -> wait — via a
bounded 8-worker thread pool, reusing the SAME WMS fault endpoints
`tests/faults/` already proves correct (`partial_commit` -> DIVERGED,
`return_200_without_commit`/`return_500_before_commit` -> OUTCOME_UNKNOWN,
plus propose-time DENIED_POLICY/DENIED_AUTHORIZATION/INSUFFICIENT_EVIDENCE
via parameter choice). Run sequence: generate 116 V1 decisions -> `make
deploy-v2` -> generate 116 V2 decisions -> `make deploy-v3`. Result:
**232 live decisions, 210 complete action/outcome chains** (>= the spec's
200 minimum), recorded in `experiments/exp-000/results/historical-corpus.json`.

**Found and fixed mid-generation, the costliest bug of this phase**: the
first full run had every single decision time out waiting for
`current_inventory` to converge (175+ seconds, never converging, on writes
that should take ~3s). Root cause: the poll loop's `psycopg.connect(...)`
was never set to `autocommit=True` and never committed between polls — an
open, uncommitted SELECT-only transaction held an `AccessShareLock` on
`current_inventory` for its WHOLE lifetime, which BLOCKED
`services/projection_builder`'s own `TRUNCATE` (needs `ACCESS EXCLUSIVE`)
indefinitely. Exactly the same lock-order class Phase 6b's own
`evidence.py` freshness-retry fix already documented for a different
caller — same fix here (`conn.commit()` between polls in
`corpus_helpers.py::set_inventory_and_wait`), confirmed by direct
measurement (never converged in 175s before the fix; converged in 3s
after).

### Historical corpus — BULK tier (spec: "bulk-generate records up to
5,000 total... document which were made live vs bulk-generated")

`seed/generators/bulk_historical_decisions.py` writes DIRECTLY via
`rdf_writer.write_decision` + `store.insert_decision` (the identical
functions `propose_flow.py` calls — never a second writer), with
self-consistent synthetic evidence/gate results (built from the SAME
hashing functions real decisions use) randomly distributed across the
THREE real archived contract eras (V1, V2, V3-actions/V2-authz).
`context.is_bulk_generated=true` on every bulk record, `decision_id`
prefix `D-BULK`, so live vs bulk is always distinguishable by either
signal. Honest scope note (documented in the script's own docstring): the
gate OUTCOMES (allow/deny/require_approval) are randomly assigned, not
derived from evaluating real policy against the fabricated evidence — this
tier is for query/load testing volume, not a second replay-corpus claim.
This session's stack already carried 1,970 decisions from its own
Phase 5-7 history before this ran; 3,030 new bulk records brought the
total to exactly **5,000** (verified via a direct `SELECT count(*)`, not
the script's own self-report).

### Replay (H7) — `services/decision_service/replay.py`

`replay_decision(decision_id, conn, rdf4j_client, openfga_api_url,
opa_base_url)`:

1. Reconstructs the evidence snapshot from RDF4J's `EvidenceSnapshot`
   resource — **RDF4J-authoritative, not the Postgres index**, which
   deliberately omits `projection_row_hashes` (found empirically: every
   decision "failed" replay with a hash mismatch until this was corrected
   — recomputing from Postgres's PARTIAL copy alone silently produces a
   DIFFERENT hash than the one originally computed with all three inputs).
   New SPARQL query `contracts/queries/v1/q9_replay_authz_fields.rq` pulls
   the RDF-only fields (`requiredFactsJson`/`sourcePositionsJson`/
   `projectionRowHashesJson`/`snapshotContentHash`, plus the OpenFGA model
   id fields).
2. Recomputes `decision_content_hash` and cross-checks RDF4J against the
   Postgres index. A decision that never reached `APPROVED`
   (denied/insufficient-evidence) has NO `decision_content_hash` by design
   — treated as vacuously matching (nothing to check), not a failure
   (found live: the first full `test-replay` run failed 11/116 per version
   until this was corrected).
3. **F29's loud-failure point**: `_verify_archive` re-hashes every archived
   `contracts/<kind>/<pinned version>/` directory FRESH off disk and
   compares to what the decision pinned — a deleted or modified archived
   artifact raises `ReplayIntegrityError` immediately, before any gate
   re-runs. Never caught internally; propagates as HTTP 409 / CLI exit 2.
4. Re-runs the policy gate using the STORED `policy_result.input_json`
   against the historical package. **Two real bugs found and fixed
   building this**: (a) mixed the REST-API slash-path form with the Rego
   dotted-package form in the `opa eval` query argument — a silent
   `rego_unsafe_var_error`; (b) `opa eval` shelling out to `docker run`
   only works HOST-SIDE — decision_service's container has neither a
   docker socket nor the CLI, so the live `POST /replay/{id}` endpoint
   500'd. Fixed by preferring the ALREADY-RUNNING OPA server's REST API
   (it serves every published package simultaneously and forever, since
   the whole `contracts/policies/` tree is mounted) with `opa eval` via
   docker only as a fallback when OPA itself is unreachable — works
   identically host-side and in-container, and ~3x faster (no per-decision
   subprocess spawn: `make test-replay` dropped from ~80s to ~24s).
5. Re-runs the authorization check LIVE against the decision's own pinned
   `openfga_authorization_model_id`, with the `"recorded_only"` fallback
   documented in ADR 0004 when that model id no longer resolves (the real
   store-wipe event above exercises this fallback for the ENTIRE corpus in
   this run).

`POST /replay/{id}` (404 not found, 409 on F29 integrity failure) and
`POST /reevaluate/{id}` (separate counterfactual, `services/decision_service/replay.py::reevaluate_under_current`
— reuses the frozen evidence FACTS but rebuilds the policy input under
CURRENTLY deployed rules, never touches history). `make replay
DECISION_ID=<id>` / `make reevaluate DECISION_ID=<id>` CLIs
(`scripts/replay_cli.py`, `scripts/reevaluate_cli.py`) call the exact same
functions the HTTP endpoints do.

**Counterfactual live proof** (the capstone demonstration of H7's "never
silently apply today's policy to yesterday's decision"): a real V1 corpus
decision (quantity 95, auto-`ALLOW`ed under V1's 100-unit threshold)
replays `PASS` with its ORIGINAL "allow" verdict forever, while `make
reevaluate` on the SAME decision reports
`diverges_from_original: true`, `under_current_policy_outcome:
"require_approval"` (V2/V3's lower 80-unit threshold) — proven, not
asserted. `reevaluate_under_current` also handles the case where old
evidence lacks a field the CURRENT policy needs: a V1 snapshot has no
`reservation_ok` fact (didn't exist before V2) but DOES carry
`on_hand`/`reserved` inside `current_source_inventory` (always populated,
even when V1's own policy never read them) — derived rather than crashed,
with an explicit "cannot reevaluate" result as the honest fallback for any
OTHER shape mismatch.

### `make test-replay`: 100% PASS

`tests/replay/test_replay_corpus.py` replays every one of the 232 LIVE V1
(116) and V2 (116) decisions under the (by then) V3-deployed state — **8
passed** covering: the corpus itself (2 tests), F29 (2 tests: delete +
modify an archived policy, both restored in `finally`, both re-verified
`PASS` again afterward), projection-rebuild-after-migration (reuses Phase
4's exact `build_all`/`table_hash` mechanism, explicitly asserting a
migration has actually run first), and H13 forensic queries Q1-Q8
(`contracts/queries/v1/*.rq`, unchanged, version-agnostic by design)
answering fully for a real V1 decision after the whole V1->V2->V3
sequence — Q4 shows the decision's OWN original v1 pin, never silently
migrated.

### F28 — `scripts/compat_check.py`

Structural, not self-reported: for each `contracts/<kind>/vN/` with real
content (N>=2), coverage requires EITHER a `migrations/*/migration.json`
whose `kind_versions` map (kind -> its OWN target version — needed because
one migrations/ directory can cover kinds reaching DIFFERENT version
numbers in the same deploy, exactly this phase's own `migrations/v2_to_v3/`:
`actions` -> v3, `authorization` -> v2) declares that exact (kind, version)
pair, OR (fallback, for a kind with no `migration.json`) a numerically-
matched `migrations/v{N-1}_to_v{N}/` directory containing a script. Found
and fixed the `kind_versions` gap live: the FIRST version only matched by
version NUMBER, which would have let `authorization/v2` ride for free on
`migrations/v1_to_v2/`'s UNRELATED `migrate_rdf.py` purely because both
happened to be "version 2" of something. `make test-contracts` runs it
directly (Makefile), plus `tests/contracts/test_compat_check.py`: the real
repo tree (0 violations) and three synthetic known-bad trees (missing
migration dir, empty migration dir, `migration.json` pointing at a
nonexistent script).

### F39 — already half-built, just never exercised

`services/identity_resolver/resolver.py::IdentityResolver` already
validated `mapping_rules.yaml` at LOAD TIME with a
`ConflictingMappingRuleError` explicitly commented "F39" — from an earlier
phase, never tested. `tests/component/test_f39_invalid_mapping_rule.py`:
conflicting explicit-override entries for the same source id (the
realistic deployment error), an unknown rule kind, a pattern rule missing
`canonical_template`, and a known-negative (a structurally valid file
still loads and resolves correctly, proving the first three catch real
invalidity rather than rejecting everything).

### fault-matrix-phase7.json

`scripts/gen_fault_matrix_phase7.py`: every F01-F40 entry carried forward
from `fault-matrix-phase6b.json` unchanged except F28/F29/F39, updated to
PASS with real test node ids verified against a live `pytest
--collect-only` run (same convention Phase 6b's own generator used).
**38 PASS, 2 NOT_TESTED** (F30 needs Phase 9's agent/MCP layer, F40 needs
Phase 10's observability layer — both explicitly out of this phase's
scope, untouched).

### What Phase 8 (A/B baseline) needs from here

- `contracts/manifests/deployed_version.json` + `services/common/contract_versions.py::deployed_version()`
  is now the ONE place any future phase checks "what contract version is
  live" — never hardcode "v1" again anywhere in this codebase (two
  pre-existing Phase 4/5 tests already had to be fixed for exactly this:
  `tests/integration/test_forensic_queries.py` and
  `tests/integration/test_projection_differential.py`).
- The stack is LEFT at its real, final Phase 7 state:
  `ontology=v2, shapes=v2, actions=v3, policies=v2, authorization=v2,
  identity=v1, projections=v2, reconciliation=v1` — Phase 8's baseline
  comparison should measure against THIS state, not assume v1 everywhere.
- `contracts/manifests/openfga_model_ids.json` (kind version -> real
  OpenFGA `authorization_model_id`) is the pattern for any future phase
  that needs to pin a real external-system identifier alongside a
  content-hash version — see `docs/adr/0004` for the full reasoning on
  why a content hash alone isn't enough for OpenFGA specifically.
- The `memory` OpenFGA datastore engine is a real, now-OBSERVED
  operational risk (not just a theoretical one) for any phase that keeps
  this stack running for hours — if authorization replay/checks start
  returning unexpected `UNAVAILABLE`/`recorded_only`, re-run
  `services/decision_service/bootstrap_openfga.py` then
  `migrations/v2_to_v3/migrate_authz.py` before assuming a code bug.
