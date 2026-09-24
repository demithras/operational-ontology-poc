.PHONY: up down reset seed test test-unit test-contracts test-component test-integration \
        test-stateful test-destructive test-determinism test-faults test-replay bench \
        bench-phase5 experiment report replay ensure-env wait-healthy wait-converged \
        wait-connectors rebuild-projections

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
	$(VENV_PY) services/decision_service/bootstrap_openfga.py

## Delegates to services/common/wait_healthy.py (see its docstring for why
## this stopped being a plain bash/grep loop in Phase 5: openfga/opa have no
## shell inside their images, so they declare no docker-level healthcheck at
## all, and a naive "grep -v healthy" loop would wait forever on them).
wait-healthy:
	@echo "waiting for all compose services to report running (+healthy where a healthcheck is configured)..."
	@$(VENV_PY) services/common/wait_healthy.py

down:
	docker compose down

## Full reset: drop EVERY named volume (Postgres AND RDF4J — `docker compose
# down -v` per docs/experiment/briefs/phase4fix.md "after down -v, all CDC
# state ... must be reset too"). Kafka and Connect have no named volume at
# all (docker-compose.yml) — a plain container recreation already wipes
# their broker/internal-topics state every time, `-v` or not, so there is
# no separate "Kafka volume" to drop; verified empirically (see
# docs/experiment/implementation-notes.md Phase 4 fix section). Ends only
# once connectors are confirmed RUNNING (wait-connectors) — a bare "up"
# alone does not guarantee that (register_connectors.py's PUT only means
# Kafka Connect accepted the config, not that the task/replication slot
# actually exists yet).
reset: ensure-env
	docker compose down -v
	$(MAKE) up
	$(MAKE) wait-connectors

## Deterministic seed-dataset generator (seed/generators/generate.py) +
# load step into the running erp/mes/wms databases (seed/load.py), writing
# seed/out/identity_truth.json. Same SEED => byte-identical generated
# dataset (seed/out/manifest.json's combined_sha256) and, per
# docs/experiment/briefs/phase2.md item 3, the same loaded WMS state. Ends
# only once the WHOLE pipeline has converged (wait-converged, phase4fix.md
# "a single readiness contract") — never returns while ingestion is still
# mid-drain of the CDC backlog this seed just produced.
seed: ensure-env
	$(VENV_PY) seed/generators/generate.py --seed $(SEED)
	$(VENV_PY) seed/load.py --seed $(SEED)
	$(MAKE) wait-converged

## The single readiness contract every one of up/seed/reset ultimately
# blocks on (docs/experiment/briefs/phase4fix.md): connectors RUNNING,
# ingestion consumer lag 0 against CURRENT Kafka high-watermarks, RDF4J
# contains the canonical fixture (WO-42, LOT-A-PX17), and the
# work_order_risk projection has a WO-42 row. Prints exactly what is still
# missing and exits non-zero on timeout — never fakes convergence.
wait-converged: ensure-env
	$(VENV_PY) services/ingestion/wait_converged.py

## Same contract, but skips the RDF4J-fixture / projection checks — for
# right after a bare `make up`/`make reset`, before any `make seed` has
# run, when the source tables are still genuinely empty and those two
# checks could never be satisfied.
wait-connectors: ensure-env
	$(VENV_PY) services/ingestion/wait_converged.py --no-data

## Run the Phase 1 pure reference-model test suite (tests/model/).
test-unit:
	$(VENV_PY) -m pytest tests/model -q

## docs/experiment/spec/13_repository_contract.md "make test-integration".
# Requires the stack to be up (`make up`) and seeded (`make seed`).
# tests/integration/test_seed_determinism.py is EXCLUDED here (see
# test-destructive below, docs/experiment/briefs/phase4fix.md) — it is the
# one integration test that tears the stack down and rebuilds it
# (subprocess `make reset` x2), which must never happen inside a plain
# `make test` run.
test-integration: ensure-env
	$(VENV_PY) -m pytest tests/integration -q --ignore=tests/integration/test_seed_determinism.py

## Destructive tests: anything that runs `make reset`/`down` itself.
# Currently just test_seed_determinism.py (docs/experiment/briefs/phase2.md
# item 3's same-seed-same-state proof, which by construction must reset
# the stack twice). NEVER part of `make test` — running it concurrently
# with anything else touching the shared stack (another `make test`,
# `make bench`, ...) resets THEIR stack out from under them
# (docs/experiment/briefs/phase4fix.md item 3: this, not an external
# process, was the real cause of the Phase 4 flakiness). Run it alone.
test-destructive: ensure-env
	$(VENV_PY) -m pytest tests/integration/test_seed_determinism.py -q

test-determinism: test-destructive

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
#
# Phase 5 (docs/experiment/briefs/phase5.md item 3): also runs the OpenFGA
# model tests (`fga model test`) and OPA policy tests (`opa test
# --fail-on-empty`), each via its own docker CLI image (tests/contracts/
# test_openfga_model.py / test_opa_policies.py shell out to `docker run`,
# same pattern as the rest of this file — needs DOCKER_CONFIG, see
# docs/experiment/briefs/common.md).
test-contracts:
	$(VENV_PY) -m pytest tests/contracts -q

## docs/experiment/spec/08_test_strategy.md "Level 2 — Component tests".
# Currently: services/identity_resolver (exact/quarantine/metamorphic
# against seed/out/identity_truth.json — skips with a reason if
# `make seed` hasn't been run).
test-component:
	$(VENV_PY) -m pytest tests/component -q

## docs/experiment/spec/07_versioning_and_replay.md "Projection rebuild":
# truncate + reconstruct all four hot-projection tables from the semantic
# core and prove hash(rebuilt) == hash(before) over deterministic business
# fields (tests/integration/test_projection_rebuild.py is the pass/fail
# authority; this target also fails loudly on its own — see
# services/projection_builder/rebuild.py).
rebuild-projections: ensure-env
	$(VENV_PY) -m services.projection_builder.rebuild

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

## docs/experiment/spec/08_test_strategy.md "Performance methodology" /
# docs/experiment/spec/01_hypotheses.md H6 (partial: hot-projection read
# path only — gate evaluation / decision proposal latency are Phase 5+).
# Writes experiments/exp-000/results/bench-phase4.json. Exits non-zero ONLY
# if the locked hot_read_p95_ms SLO (experiments/exp-000/manifest.yaml)
# fails — never tuned post hoc.
bench: ensure-env
	$(VENV_PY) tests/performance/bench_phase4.py
	$(MAKE) bench-phase5

## docs/experiment/briefs/phase5.md item 9: gate evaluation p95 (authz/
## policy/SHACL/persistence stages) and end-to-end proposal-path p95,
## against the H6/acceptance-criteria SLOs (300ms/500ms). Writes
## experiments/exp-000/results/bench-phase5.json. Requires the full stack
## (postgres/rdf4j/openfga/opa/wms/decision_service) reachable.
bench-phase5: ensure-env
	$(VENV_PY) tests/performance/bench_phase5.py

experiment:
	@echo "not implemented yet — Phase 10 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

report:
	@echo "not implemented yet — Phase 10 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

replay:
	@echo "not implemented yet — Phase 7 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2
