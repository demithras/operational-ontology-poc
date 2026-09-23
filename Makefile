.PHONY: up down reset seed test test-unit test-contracts test-integration \
        test-stateful test-faults test-replay bench experiment report replay

VENV_PY := .venv/bin/python
SEED ?= 42

# ---------------------------------------------------------------------------
# Implemented (Phase 0 + Phase 1)
# ---------------------------------------------------------------------------

## Run the Phase 1 pure reference-model test suite (tests/model/).
test-unit:
	$(VENV_PY) -m pytest tests/model -q

## make test aggregates all non-performance mandatory tests
# (docs/experiment/spec/13_repository_contract.md "Mandatory commands").
# For Phase 0+1 the only implemented layer is tests/model/, so `test` is
# currently equivalent to `test-unit`; later phases extend this target as
# tests/contracts, tests/component, tests/integration, tests/faults land.
test: test-unit

## Deterministic seed-dataset generator (seed/generators/generate.py).
# Same SEED => byte-identical seed/out/ (verified by
# seed/out/manifest.json's combined_sha256).
seed:
	$(VENV_PY) seed/generators/generate.py --seed $(SEED)

## test-stateful: Phase 1's Hypothesis stateful machine + bug-detection
# suite already exist (tests/model/test_stateful.py,
# tests/model/test_bug_detection.py) — later phases will broaden this to
# tests/stateful/ against the real system, but aliasing it to today's
# pure-model stateful tests is explicitly allowed
# (task instructions: "test-stateful as alias is fine").
test-stateful:
	$(VENV_PY) -m pytest tests/model/test_stateful.py tests/model/test_bug_detection.py -q

# ---------------------------------------------------------------------------
# Not implemented yet — never fake success. Each prints which phase
# (docs/experiment/spec/12_implementation_plan.md) is responsible and exits
# 2, per experiments/exp-000/manifest.yaml `exit_codes`.
# ---------------------------------------------------------------------------

up:
	@echo "not implemented yet — Phase 2 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

down:
	@echo "not implemented yet — Phase 2 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

reset:
	@echo "not implemented yet — Phase 2 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

test-contracts:
	@echo "not implemented yet — Phase 3 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

test-integration:
	@echo "not implemented yet — Phase 2 (see docs/experiment/spec/12_implementation_plan.md)"
	@exit 2

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
