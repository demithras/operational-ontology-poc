# Operational Ontology POC

A falsifiable local proof-of-concept testing whether a small, fully local,
open-source **operational ontology** can drive a real operational decision,
enforce hard authorization/policy/conformance gates before external effects,
observe real-world outcomes instead of trusting its own command path, and
preserve enough versioned evidence to reconstruct a decision months later —
and whether any of that is worth its added complexity over a simpler
baseline.

Full specification: [`docs/experiment/spec/`](docs/experiment/spec/)
(start with `00_thesis.md` and `README.md` in that folder). Experiment lock
for this run: [`experiments/exp-000/manifest.yaml`](experiments/exp-000/manifest.yaml).

## Phase status

Build order and exit criteria: `docs/experiment/spec/12_implementation_plan.md`.

| Phase | What | Status |
|---|---|---|
| 0 | Experiment lock (hypothesis ledger, thresholds, canonical fixtures, ADR template) | done |
| 1 | Pure domain model (`reference_model/`) — deterministic transitions, invariants, canonical incident, Hypothesis state machine | done |
| 2 | Fake ERP/MES/WMS source systems | done |
| 3 | Semantic core (RDF4J, ontology, PROV-O, SHACL) + CDC ingestion (Kafka, Debezium) | done |
| 4 | Hot projections (`work_order_risk`, `transfer_candidates`, `current_inventory`, `action_eligibility_summary`) in PostgreSQL, derived from the semantic core via SPARQL | done |
| 4fix | Test-suite stability: single readiness contract (`make wait-converged`), destructive tests isolated into `make test-destructive`, root-caused and fixed the flaky CDC-convergence check | done (tag `poc-v0.4.1-stable`) |
| 5 | Decision service + gates (OpenFGA, OPA, SHACL gate capture) | done |
| 6 | Durable action runtime (Temporal, WMS action, idempotency, CDC, reconciliation) | done (tag `poc-v0.6-actions`) |
| 6b | Complete the fault matrix (F01-F40; worker-crash/CDC-delay/Kafka-outage/kill/network fault tests; F34 action-version pinning implemented; two real concurrency bugs + a SPARQL/IRI injection vulnerability found and fixed) | done (tag `poc-v0.6.1-faults`) |
| 7 | Contract versioning / replay | pending |
| 8 | A/B baseline (conventional relational implementation) | pending |
| 9 | Agent / MCP layer | pending |
| 10 | Final attack (full stateful suite, fault matrix, mutation tests, load, replay, A/B) | pending |

Phase 1 runs in **lite mode taken to its logical extreme**: pure Python, no
infrastructure at all (no RDF4J, no Postgres, no OpenFGA/OPA, no Temporal,
no Kafka/Debezium, no LLM). See
[`docs/adr/0001-lite-mode-for-phase-1.md`](docs/adr/0001-lite-mode-for-phase-1.md)
for what this does and does not let the experiment claim.

## Repository layout

Matches `docs/experiment/spec/13_repository_contract.md`. Directories for
phases not yet implemented exist as empty skeletons (`.gitkeep`) so the
target layout is visible from commit one.

```text
contracts/          ontology/shapes/actions/policies/authorization/projections/manifests (Phase 3+)
services/            fake ERP/MES/WMS, decision service, action worker, etc. (Phase 2+)
reference_model/     Phase 1 — pure Python oracle (state.py, transitions.py, invariants.py, derive.py)
migrations/          contract version migrations (Phase 7)
seed/                deterministic dataset generator (seed/generators/) + fixtures (seed/fixtures/)
tests/               model/ (Phase 1, implemented), contracts/, component/, integration/,
                     stateful/, faults/, replay/, performance/, ab/, agent/ (later phases)
experiments/         exp-000/ — this experiment's locked manifest, seeds, and results
observability/       OpenTelemetry config (later phases)
docs/adr/            architecture decision records
docs/experiment/spec/  the specification pack this repo implements
```

## Running it

Requires Python 3.11+ (developed against 3.14).

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

make test          # pytest tests/model — Phase 1 reference-model suite
SEED=42 make seed  # deterministic seed dataset into seed/out/ (gitignored)
```

To also bring up Phase 2's fake ERP/MES/WMS source systems (requires
Docker):

```bash
cp .env.example .env       # local-only docker-compose credentials (gitignored)
make up                    # postgres:16 + erp/mes/wms, waits for health
SEED=42 make seed          # generate + load into the running services
make test-integration      # tests/integration/ against the real stack
make down                  # or `make reset` to wipe and start clean
```

ERP/MES/WMS are plain FastAPI + Postgres services on host ports 15401/
15402/15403 (Postgres itself on 15432). Since Phase 3, `make up` also
brings up the semantic core + CDC pipeline — Kafka, Debezium Connect,
RDF4J, and the `services/ingestion` consumer
(docs/adr/0002-cdc-now-not-deferred.md: CDC is built now, not deferred to
Phase 6) — and idempotently registers the Debezium connectors + bootstraps
the RDF4J `oo` repository (ontology + SHACL shapes). See
`docs/experiment/implementation-notes.md` for the full port/endpoint/design-
decision log.

Since Phase 4, `make up` also brings up `services/projection_builder`
(short-poll loop, `OO_PROJECTION_POLL_INTERVAL_S`, default 3s), which
derives the four hot-projection tables in `ontology_hot` — `work_order_risk`,
`transfer_candidates`, `current_inventory`, `action_eligibility_summary` —
from SPARQL queries against RDF4J only (never the source Postgres
databases). `make rebuild-projections` truncates and reconstructs them and
proves `hash(rebuilt) == hash(before)` over deterministic business fields.
`make bench` measures hot-projection read latency (warm/cold) against the
locked `hot_read_p95_ms` SLO plus a counter-test (the same information via
direct SPARQL), writing `experiments/exp-000/results/bench-phase4.json`.

Since Phase 5, `make up` also brings up `openfga` (authorization,
memory-store, host port 15481), `opa` (contextual policy, loading
`contracts/policies/v1` as a mounted bundle, host port 15482), and
`services/decision_service` (the governed decision API, host port 15410) —
and idempotently bootstraps the OpenFGA store/model/tuples from
`contracts/authorization/v1/`. `POST /decisions/propose` runs the full
evidence → authorization (OpenFGA) → policy (OPA) → SHACL-validated RDF4J
write pipeline from `docs/experiment/spec/06_decision_and_action_runtime.md`;
`GET /decisions/{id}`, `POST /decisions/{id}/approve` (human approval, F33
hash-mismatch rejection), and `POST /decisions/{id}/execute` /
`POST /replay/{id}` (verified-immutable-tuple / 501 stub through Phase 7)
round out the API surface. `make test-contracts` now also runs the OpenFGA
model tests (`fga model test`) and OPA policy tests (`opa test
--fail-on-empty`), each via its own docker CLI image. `make bench-phase5`
(folded into `make bench`) measures per-gate latency (authorization/policy/
SHACL-RDF4J/Postgres) plus the end-to-end proposal path against the locked
`gate_evaluation_p95_ms`/`decision_proposal_p95_ms` SLOs, writing
`experiments/exp-000/results/bench-phase5.json`.

Since Phase 6, `make up` also brings up Temporal (its own dedicated
Postgres, frontend gRPC on host port 15473, optional Web UI on 15474),
`services/action_worker` (a Temporal worker, health port 15486), and
`services/reconciliation` (an independent CDC re-check loop, H12, health
port 15487) — and idempotently waits for Temporal's `default` namespace.
`POST /decisions/{id}/execute` now really starts (or idempotently reuses)
an `ActionExecutionWorkflow`, which calls WMS/ERP/MES with the
`action_execution_id` as idempotency key, waits for the CDC-observed
`fac:WmsTransferRecord` (never re-querying WMS live), evaluates the
ActionType's outcome predicate, and sets `OBSERVED_SUCCESS` / `DIVERGED` /
`OUTCOME_UNKNOWN` / `EXECUTION_FAILED` — auto-compensating (`reverse_transfer`)
where the contract says `compensatable`. `GET /executions/{id}` /
`GET /outcomes/{id}` are real. `make test-faults` drives this end to end
against the real stack (F01-F40 from `docs/experiment/spec/09_failure_and_adversarial_matrix.md`
— idempotency, divergence, the 100/80/80 concurrency race, worker-crash
kill/restart, CDC delay/dedup/reorder, Kafka/Temporal outage, action-
version pinning, kill tests for every long-running service, network
faults; `experiments/exp-000/results/fault-matrix-phase6b.json` is the
full per-fault status) — run it alone (real `docker compose kill`/`stop`/
`start` throughout), never inside `make test`. `make bench-phase6` (folded into `make bench`)
measures external-action duration / CDC-observation lag / end-to-end
execution time, writing `experiments/exp-000/results/bench-phase6.json`
(no SLO gate locked for these three — measurement reporting).

Every other mandatory command from the repository contract (`make
test-replay`, `make experiment`, `make report`, `make replay
DECISION_ID=<id>`) prints which phase it belongs to and exits `2` —
nothing is faked as passing before its phase actually lands. `make
test-stateful` is already live: it aliases to Phase 1's own Hypothesis
stateful/bug-detection tests. `make test-contracts` (Phase 3+) is live:
SHACL positive/negative fixtures via pyshacl, the same shapes proven
transactionally against the real RDF4J repository, plus (Phase 5) the
OpenFGA/OPA suites above. `make test`
runs `tests/model/` and `tests/contracts/` always, and `tests/component/` +
`tests/integration/` too if the stack is reachable (otherwise it prints a
clear skip, per the same honesty rule) — `tests/faults/` is intentionally
NOT part of `make test` (see `make test-faults` above).

## What Phase 1 proves (and doesn't)

`reference_model/` is the Level 0 oracle from
`docs/experiment/spec/08_test_strategy.md`: frozen-dataclass `WorldState`,
pure `transition(state, ...) -> (new_state, result)` functions, and
`invariants.py`. It implements the canonical incident and negative cases
from `docs/experiment/spec/03_domain_scenario.md`, the decision-gate
pipeline (evidence → authorization → policy → conformance → approved) from
`docs/experiment/spec/06_decision_and_action_runtime.md`, the concurrency
race and idempotency contracts, and a Hypothesis `RuleBasedStateMachine`
(`tests/model/_machine.py`) whose rules cover every pure-model verb from
`08_test_strategy.md`'s stateful-testing example list.

Four bugs are deliberately injectable (`reference_model.state.ALL_BUGS`) and
each is proven to be caught and shrunk to a minimal failing step sequence by
`tests/model/test_bug_detection.py`; the shrunk sequences are recorded under
`experiments/exp-000/results/shrunk-failures/`.

It does **not** yet prove anything about real CDC, real durable execution,
real network partitions, or real gate services (OpenFGA/OPA/SHACL) — that
is Phases 2–6, and hypothesis conclusions that depend on them remain
`PENDING` in `experiments/exp-000/manifest.yaml` until then.
