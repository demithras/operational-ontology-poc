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
| 3 | Semantic core (RDF4J, ontology, PROV-O, SHACL) | pending |
| 4 | Hot projection (`work_order_risk`, `transfer_candidates`) | pending |
| 5 | Decision service + gates (OpenFGA, OPA, SHACL gate capture) | pending |
| 6 | Durable action runtime (Temporal, WMS action, idempotency, CDC, reconciliation) | pending |
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
15402/15403 (Postgres itself on 15432) — see
`docs/experiment/implementation-notes.md` for the full port/endpoint/design-
decision log.

Every other mandatory command from the repository contract
(`make test-contracts`, `make test-faults`, `make test-replay`, `make
bench`, `make experiment`, `make report`, `make replay DECISION_ID=<id>`)
prints which phase it belongs to and exits `2` — nothing is faked as
passing before its phase actually lands. `make test-stateful` is already
live: it aliases to Phase 1's own Hypothesis stateful/bug-detection tests.
`make test` runs `tests/model/` always, and `tests/integration/` too if the
Phase 2 stack is reachable (otherwise it prints a clear skip, per the same
honesty rule).

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
