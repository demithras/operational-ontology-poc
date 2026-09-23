.PHONY: up down reset seed test test-unit test-contracts test-component test-integration \
        test-stateful test-faults test-replay bench experiment report replay \
        ensure-env wait-healthy

SHELL := /usr/bin/env bash
VENV_PY := .venv/bin/python
SEED ?= 42

# ---------------------------------------------------------------------------
# Implemented (Phase 0 + Phase 1 + Phase 2)
# ---------------------------------------------------------------------------

# .env holds local-only docker-compose credentials (db/init/00_init.sh,
# docker-compose.yml variable substitution, seed/load.py, tests/integration/).
# Never committed (see .gitignore); copied from the tracked template on
# first use so `make up`/`make seed` work out of the box.
ensure-env:
	@test -f .env || cp .env.example .env

## Build + start the full stack (Postgres + erp/mes/wms + Phase 3's Kafka/
# Debezium Connect/RDF4J/ingestion — docs/adr/0002-cdc-now-not-deferred.md),
# block until every container reports healthy (docker-compose healthcheck:),
# then idempotently register the Debezium connectors and bootstrap the
# RDF4J "oo" repository (ontology + SHACL shapes). Both steps are safe to
# re-run (PUT .../connectors/{name}/config is create-or-update;
# bootstrap_rdf4j.py clears+reloads its two graphs every time).
up: ensure-env
	docker compose up -d --build
	$(MAKE) wait-healthy
	$(VENV_PY) services/ingestion/register_connectors.py
	$(VENV_PY) services/ingestion/bootstrap_rdf4j.py

wait-healthy:
	@echo "waiting for postgres/erp/mes/wms/kafka/connect/rdf4j/ingestion to report healthy..."
	@for i in $$(seq 1 60); do \
		unhealthy=$$(docker compose ps --format '{{.Name}} {{.Health}}' | grep -v 'healthy' | grep -v '^$$' || true); \
		if [ -z "$$unhealthy" ]; then echo "all services healthy"; exit 0; fi; \
		sleep 2; \
	done; \
	echo "timed out waiting for healthy services:"; docker compose ps; exit 1

down:
	docker compose down

## Full reset: drop the Postgres volume (all seeded/mutated data) and start clean.
reset: ensure-env
	docker compose down -v
	$(MAKE) up

## Deterministic seed-dataset generator (seed/generators/generate.py) +
# load step into the running erp/mes/wms databases (seed/load.py), writing
# seed/out/identity_truth.json. Same SEED => byte-identical generated
# dataset (seed/out/manifest.json's combined_sha256) and, per
# docs/experiment/briefs/phase2.md item 3, the same loaded WMS state.
seed: ensure-env
	$(VENV_PY) seed/generators/generate.py --seed $(SEED)
	$(VENV_PY) seed/load.py --seed $(SEED)

## Run the Phase 1 pure reference-model test suite (tests/model/).
test-unit:
	$(VENV_PY) -m pytest tests/model -q

## docs/experiment/spec/13_repository_contract.md "make test-integration".
# Requires the stack to be up (`make up`) and seeded (`make seed`).
test-integration: ensure-env
	$(VENV_PY) -m pytest tests/integration -q

## test-stateful: Phase 1's Hypothesis stateful machine + bug-detection
# suite already exist (tests/model/test_stateful.py,
# tests/model/test_bug_detection.py) — later phases will broaden this to
# tests/stateful/ against the real system, but aliasing it to today's
# pure-model stateful tests is explicitly allowed
# (task instructions: "test-stateful as alias is fine").
test-stateful:
	$(VENV_PY) -m pytest tests/model/test_stateful.py tests/model/test_bug_detection.py -q

## make test aggregates all non-performance mandatory tests
# (docs/experiment/spec/13_repository_contract.md "Mandatory commands").
# tests/model/ + tests/contracts/ always run (contracts' pyshacl fixture
# tests need no docker stack; its RDF4J-transactional tests self-skip with
# an explicit reason if the "oo" repository isn't reachable — see
# tests/contracts/test_shacl_rdf4j_transactional.py). tests/component/ and
# tests/integration/ only run if the stack is reachable — otherwise this
# prints a clear skip rather than silently omitting it or faking a pass
# (common.md honesty rule; phase3.md item 6: "make test includes the
# contracts + component tests").
test: test-unit test-contracts
	@if curl -fsS -o /dev/null --max-time 2 "http://localhost:$${WMS_HTTP_PORT:-15403}/health" 2>/dev/null; then \
		$(MAKE) test-component; \
		$(MAKE) test-integration; \
	else \
		echo "SKIP: tests/component/, tests/integration/ (stack not reachable — run 'make up && make seed' first)"; \
	fi

## docs/experiment/spec/08_test_strategy.md "Level 1 — Contract/unit
# tests": SHACL positive/negative fixtures (pyshacl, in-process) plus the
# RDF4J-transactional proof of the same shapes (self-skips if the "oo"
# repository isn't reachable). CI gate (13_repository_contract.md): "SHACL
# negative fixture unexpectedly conforms" -> these tests fail.
test-contracts:
	$(VENV_PY) -m pytest tests/contracts -q

## docs/experiment/spec/08_test_strategy.md "Level 2 — Component tests".
# Currently: services/identity_resolver (exact/quarantine/metamorphic
# against seed/out/identity_truth.json — skips with a reason if
# `make seed` hasn't been run).
test-component:
	$(VENV_PY) -m pytest tests/component -q

# ---------------------------------------------------------------------------
# Not implemented yet — never fake success. Each prints which phase
# (docs/experiment/spec/12_implementation_plan.md) is responsible and exits
# 2, per experiments/exp-000/manifest.yaml `exit_codes`.
# ---------------------------------------------------------------------------

test-faults:
	@echo "not implemented yet — Phase 6 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

test-replay:
	@echo "not implemented yet — Phase 7 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

bench:
	@echo "not implemented yet — Phase 4 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

experiment:
	@echo "not implemented yet — Phase 10 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

report:
	@echo "not implemented yet — Phase 10 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

replay:
	@echo "not implemented yet — Phase 7 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2
