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
| 7 | Contract versioning / replay (V1->V2 ontology+policy+action evolution, V2->V3 authorization-model evolution, live-through-real-service historical corpus (232 decisions, 210 complete chains) + bulk corpus to 5,000, `services/decision_service/replay.py` — H7 proven: `make test-replay` 100% PASS across V1/V2 under the V3-deployed state — plus F28/F29/F39 closed) | superseded by 7b (`poc-v0.7-replay` — authz replay was fail-open, see 7b) |
| 7b | Honest replay: real authorization replay (historical OpenFGA tuple snapshot + `contextual_tuples`, replacing the fail-open `recorded_only` fallback the orchestrator's audit caught — R4/ADR 0004 closed for real), bulk corpus (5,159 decisions) now generated from REAL policy/authz evaluation instead of random outcomes, corpus regenerated on a true `make reset` (110 V1 + 130 V2 live, 216 complete chains) with two source-level fixes (`contracts/manifests/baseline_v1.json` + `make up` auto-reset, `historical_corpus.py --version` self-verifying) so deployed-contract-version drift can't recur — `make test-replay` 10/10 passed, all 740 sampled decisions PASS with live/not_applicable authz mode | done (tag `poc-v0.7.1-replay`) |
| 8 | A/B baseline: step 0 explicit `GATE_UNAVAILABLE` status + `PASS_FAIL_CLOSED_VERIFIED` replay class; `services/baseline` (Variant A — own CDC consumer/Postgres/Temporal worker, reusing authz/policy/action-type/identity-resolver/outcome-eval code verbatim); A/B experiment (`tests/ab`, `make ab`, workloads W1-W7 — 500/500 decision-match rate between variants and vs. the reference-model oracle across a full W7 corpus; ontology's ingestion lag ~5x baseline's under the same measurement) | done (tag `poc-v0.8-baseline`) |
| 9 | Agent / MCP layer: `services/mcp` (7 tools only — get_object/query_work_order_risk/list_transfer_candidates/propose_transfer_inventory/get_decision/execute_approved_decision/explain_decision; no run_sql/write_triple/approve tool exists), `tests/agent` deterministic adversarial suite (21 tests, F04/F30-F34) driven against the real MCP server, `scripts/agent_llm_probe.py` (optional real-LLM sub-experiment, SKIPPED — no API key this session) — plus step 0's forensic-query scaling fix (q1-q8 GRAPH-scoped, reproduced the old unscoped q5's `httpx.ReadTimeout` directly against the corpus) and historical-corpus rebuild (5,002 decisions) | done (tag `poc-v0.9-agent`) |
| 10a | Hardening: fixed a real projection-rebuild deadlock at the source (`TRUNCATE`->`DELETE FROM` + an advisory lock, `services/projection_builder`) + a writer-vs-writer race the fix itself exposed; load-aware measurement (`services/common/host_load.py`); live 503-not-403 proof across an OpenFGA restart warm-up window; a Hypothesis stateful/differential suite against the REAL stack (`tests/stateful`, 14-rule `LiveTransferMachine` + a dedicated `IdempotencyBugHuntMachine` that found and shrunk a deliberately injected H4 violation to a 1-step repro); mutation testing (`scripts/mutate.py` + `tests/mutation`, all 5 spec-08 categories confirmed RED-on-assertion with green controls, `6 passed in 66.46s`); minimal OpenTelemetry tracing + F40 closed (fault matrix now 40/40 PASS, 0 NOT_TESTED) | done |
| 10afix | Fixed the 2 residual `make test` failures Phase 10a disclosed (`test_decision_service_protected_transfer.py`/`test_forensic_queries_phase6.py`, both root-caused as scavenged-real-seed-state flakes, not host contention): both tests now build fully synthetic, self-contained at-risk/HIGH-priority work-order preconditions (`tests/integration/decision_helpers.py::create_at_risk_work_order_and_wait`) via a new MES test-mode endpoint (`POST /_test/work_orders/{id}`) instead of scavenging a live `transfer_candidates`/`work_order_risk` route — `make test` 73/73 integration passed, verified 3x back to back plus reverse-file-order and isolation runs | done |
| 10b | `make experiment`/`make report` implemented for real (exp-001/002/003); fair evolution comparison rebuilt via the pipeline's own fresh reset so V1-era history is built under REAL V1 SHACL shapes (not just a version label); a fresh stack now auto-advances to the product's current contracts by default; 5,000-decision bulk corpus both variants; H13 forensic-query timing; full clean-machine DoD run; 3 rounds of orchestrator-reviewed derivation-logic bugs found and fixed (F27 test race, H2/H14/hot-read-p95/H11-like-for-like/H6 + a full None-propagation sweep), with a 61-test regression suite (`tests/experiment/`) added so they can't silently regress — **exp-003 is the authoritative final result: exit code 0, `can_decide_now: PASS`, `can_prove_why_later: PASS`, 310/310 tests, 40/40 faults, H1-H10/H12-H14 SUPPORTED, H11 REJECTED (honest: the ontology's one apparent advantage was PARITY once tested like-for-like against the baseline)** | done (tag `poc-v1.0-experiment`) |

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
memory-store, host port 15481), `opa` (contextual policy, loading the
WHOLE `contracts/policies/` tree — every published version's bundle stays
simultaneously servable, since Phase 7 — as a mounted bundle, host port
15482), and `services/decision_service` (the governed decision API, host
port 15410) — and idempotently bootstraps the OpenFGA store/model/tuples
from `contracts/authorization/v1/`. `POST /decisions/propose` runs the full
evidence → authorization (OpenFGA) → policy (OPA) → SHACL-validated RDF4J
write pipeline from `docs/experiment/spec/06_decision_and_action_runtime.md`;
`GET /decisions/{id}`, `POST /decisions/{id}/approve` (human approval, F33
hash-mismatch rejection), and `POST /decisions/{id}/execute` round out the
Phase 5/6 API surface. Since Phase 7, `POST /replay/{id}` (H7: reconstructs
the evidence snapshot, re-runs the policy/authorization gates against the
ARCHIVED contract versions a decision pinned, 409s loudly per F29 if an
archived artifact was deleted/modified) and `POST /reevaluate/{id}` (the
separate, never-history-overwriting counterfactual — "what would TODAY's
rules decide?") complete it — see
`docs/experiment/implementation-notes.md`'s Phase 7 section and
`docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md`.
`make test-contracts` now also runs the OpenFGA model tests (`fga model
test`) and OPA policy tests (`opa test --fail-on-empty`), each via its own
docker CLI image, parametrized over every published contract version.
`make bench-phase5`
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

Since Phase 7, `contracts/manifests/deployed_version.json` records which
`contracts/<kind>/vN/` directory is CURRENTLY live, independently per kind
(`ontology`, `shapes`, `actions`, `policies`, `authorization`, `identity`,
`projections`, `reconciliation`) — "deploying" a new contract version is a
data-only edit to that one file, picked up on the next request with no
container restart (`services/common/contract_versions.py::deployed_version()`
reads it fresh every call). `migrations/v1_to_v2/` (ontology retires
`fac:availableQuantity`, policy/action/projection evolve alongside) and
`migrations/v2_to_v3/` (a second, deliberately different kind of breaking
change — a new, non-inherited OpenFGA authorization relation, requiring a
real tuple migration) are the two real evolutions this experiment ran;
`make deploy-v2` / `make deploy-v3` apply them against the live stack.
`seed/generators/historical_corpus.py` created 232 decisions through the
real decision service across both eras (210 with complete action/outcome
chains, including denied/failed/diverged/unknown outcomes via the same
fault-injection endpoints `tests/faults/` uses);
`seed/generators/bulk_historical_decisions.py` fills the rest of a
5,000-decision corpus for query/load testing via the same production write
path, self-reported as `bulk` (never conflated with the live corpus).
`POST /replay/{id}` / `make replay DECISION_ID=<id>` reconstruct a
decision's evidence, re-run its policy/authorization gates against the
ARCHIVED contract versions it pinned, and fail loudly (F29, HTTP 409) if
an archived artifact was deleted or modified since — `make test-replay`
replays every V1 and V2 corpus decision under the (by then) V3-deployed
state, 100% PASS required. `POST /reevaluate/{id}` / `make reevaluate
DECISION_ID=<id>` is the separate counterfactual ("what would today's
rules decide?") that never overwrites history — see
`docs/experiment/implementation-notes.md`'s Phase 7 section for a live
example where the two genuinely diverge. `scripts/compat_check.py` (`make
test-contracts`) fails any published contract version lacking migration
coverage (F28); `experiments/exp-000/results/fault-matrix-phase7.json` is
the updated fault matrix (38 PASS / 2 NOT_TESTED — F30/F40 remain
Phase 9/10 scope).

`make test-stateful` is already live: it aliases to Phase 1's own Hypothesis
stateful/bug-detection tests. `make test-contracts` (Phase 3+) is live:
SHACL positive/negative fixtures via pyshacl, the same shapes proven
transactionally against the real RDF4J repository, plus (Phase 5) the
OpenFGA/OPA suites above. `make test`
runs `tests/model/` and `tests/contracts/` always, and `tests/component/` +
`tests/integration/` too if the stack is reachable (otherwise it prints a
clear skip, per the same honesty rule) — `tests/faults/` and `tests/replay/`
are intentionally NOT part of `make test` (see `make test-faults` /
`make test-replay` above). Since Phase 10b, `make experiment` / `make report`
are real (see the "Phase 10b — final experiment run" section below for the
full write-up and final result).

Since Phase 8, `make up` also brings up `services/baseline` — Variant A of
`docs/experiment/spec/10_ab_experiment.md`'s A/B experiment: a conventional
relational implementation with no RDF, no PROV graph, no SHACL (its own
`baseline` Postgres database, its own CDC consumer reading the SAME
Debezium topics under a separate Kafka consumer group, its own FastAPI
service on host port 15411 with the same propose/approve/execute/replay
API surface, its own Temporal task queue). It reuses
`services/decision_service`'s authorization/policy/action-type/hashing
code and `services/identity_resolver`/`services/action_worker`'s workflow/
outcome-evaluation code UNCHANGED — see
`docs/experiment/implementation-notes.md` Phase 8 item 1 for why literal
code reuse (not a second implementation) is this phase's central fairness
decision. `tests/ab/` (workloads W1-W7) + `make ab` run the full A/B
experiment against both live variants and write
`experiments/exp-000/results/ab-results.json` (raw metrics) +
`experiments/exp-000/results/ab-tradeoffs.md` (the trade-off table, no
weighted winner score, per spec 10). Headline result: across a 500-scenario
generated incident corpus (W7), the two variants reached the IDENTICAL
governed decision in every single case, and matched the independent
`reference_model` oracle in every case it could referee — the baseline's
ingestion lag and proposal-latency tail are measurably better under burst
load, a genuine, reported cost of the ontology's extra CDC → RDF4J →
hot-projection pipeline stage. Phase 8 step 0 (before any of this) also
closed a real acceptance-criterion gap: a dependency (OpenFGA/OPA) outage
now produces an explicit `GATE_UNAVAILABLE` status (HTTP 503) instead of a
fabricated denial, with its own `PASS_FAIL_CLOSED_VERIFIED` replay class —
see `docs/experiment/implementation-notes.md`'s Phase 8 sections for the
full write-up, including two real bugs found and fixed while building the
baseline.

Since Phase 9, `make up` also brings up `services/mcp` (host port 15490,
streamable-http + `/health`) — the agent surface `docs/experiment/spec/06_decision_and_action_runtime.md`'s
"MCP layer" section describes, exposing exactly `get_object`,
`query_work_order_risk`, `list_transfer_candidates`,
`propose_transfer_inventory`, `get_decision`, `execute_approved_decision`,
and `explain_decision` — no `run_sql`/`write_triple`/unrestricted-HTTP/
approval tool exists anywhere in the package. It always acts as one fixed
`oo:SoftwareAgent` identity (`OO_MCP_AGENT_ID`, default `agent-1`); the
human it acts on behalf of is resolved server-side from OpenFGA, never
asserted by a caller. `tests/agent/` + `make test-agent` is a deterministic
scripted "compromised planner" that drives the real server through every
spec 09 F04/F30-F34 adversarial scenario (prompt-injection-style requests,
tool-parameter tampering, undisclosed/admin tools, impersonation, stale-
decision execution, approval replay, evidence-snapshot swapping) and
asserts zero forbidden effects against real WMS ground truth — H9's
verdict rests on this suite, not on `scripts/agent_llm_probe.py`'s optional
real-model sub-experiment (`make agent-llm-probe`, SKIPPED without
`ANTHROPIC_API_KEY`). Phase 9's own step 0 also fixed a real
query-scaling bug found reviewing Phase 8: `contracts/queries/v1/q1-q8.rq`
were missing the named-graph scoping Phase 7b had only applied to q9,
which fanned out into an `httpx.ReadTimeout` once the corpus reached
thousands of decisions by the same actor — see
`docs/experiment/implementation-notes.md`'s Phase 9 section for the full
write-up.

Since Phase 10a, `make up` also brings up `otel-collector` (host port
15491, OTLP/HTTP -> a file exporter on a host bind mount,
`observability/otel/traces/`) — minimal OpenTelemetry tracing on
`services/decision_service`'s propose/approve/execute endpoints
(`services/common/tracing.py`), best-effort and F40-safe (a dead collector
never adds latency or fails a real request). `scripts/gen_traces_
reference.py` regenerates `experiments/exp-000/results/traces-reference.txt`
from real exported spans. `tests/stateful/` (`make test-stateful` still
aliases to Phase 1's own model-level suite; the real-stack one is `.venv/
bin/python -m pytest tests/stateful -q`, run alone) drives the live stack
with a Hypothesis `RuleBasedStateMachine`, differential-tested against
`reference_model` where directly comparable, and includes a dedicated
proof that Hypothesis finds and shrinks a deliberately injected bug (WMS's
own idempotency check disabled via a real test-mode toggle) to a one-step
minimal reproduction. `scripts/mutate.py` + `tests/mutation/` (run alone,
`.venv/bin/python -m pytest tests/mutation -q`) apply each of spec 08's 5
mutation categories to the REAL running implementation, confirm the
relevant suite goes RED on a genuine assertion with its paired control
staying GREEN, then revert — `experiments/exp-000/results/mutation-results.json`.
Phase 10a step 0 also fixed a real projection-rebuild deadlock at its
source (`services/projection_builder`: `TRUNCATE` -> `DELETE FROM` + a
`pg_advisory_xact_lock`, proven live over 60s of concurrent rebuild + 8
proposers) and closed F40 in the fault matrix (now 40/40 PASS, 0
NOT_TESTED) — see `docs/experiment/implementation-notes.md`'s Phase 10a
sections for the full write-up, including several real defects found
while building this phase's own tests (an OpenFGA model-versioning gap in
`bootstrap_openfga.py`'s reuse logic, and a Temporal idempotency subtlety
that made an earlier retry-testing design vacuously safe regardless of any
real bug).

## Phase 10b — final experiment run (`make experiment`/`make report`, tag `poc-v1.0-experiment`)

`scripts/run_experiment.py` (`make experiment`) creates a NEW immutable
`experiments/exp-NNN/` (manifest.yaml copying exp-000's locked thresholds
unchanged) and runs the full pipeline end to end: the fair evolution
comparison (spec 10, H7/H11 — its own destructive fresh reset so V1-era
history is built under the REAL V1 SHACL shapes, not just a version-label
pointer, then real `deploy-v2`/`deploy-v3` and a full replay sweep for
BOTH variants), the 5,000-decision bulk corpus for both variants, the
comprehensive test suite, mutation tests, the full A/B rerun (W1-W7 at
N=500), latency benchmarks (including H13 forensic-query timing on the
full corpus), the fault matrix — then derives `hypothesis-results.json`
and `final-report.md` from the real artifacts this run produced, never
hand-typed. `make report` regenerates `final-report.md` from whatever
results already exist, without re-running anything. Exit codes follow
spec 11 (0/10/11/12/13/14/15).

A genuinely fresh stack (`make up && make seed`) now auto-advances to the
product's CURRENT published contracts (today V1→V2→V3) by default
(`services/common/advance_fresh_stack_to_current.py`) — via the same real
`deploy-vN` functions `make experiment`'s own evolution comparison uses —
so `make test` right after `make seed` is green out of the box, matching
this README's own definition-of-done sequence. The evolution comparison
explicitly descends back to a genuine V1 genesis (its own `down -v`/`up`/
`seed`, `OO_SKIP_AUTO_ADVANCE=1`) when it needs to build that V1-era
history, then advances forward again the same way.

### Final result (exp-003, tag `poc-v1.0-experiment`)

```yaml
can_decide_now: PASS
can_prove_why_later: PASS

ontology_thesis:
  H1: SUPPORTED    H2: SUPPORTED    H3: SUPPORTED    H4: SUPPORTED
  H5: SUPPORTED    H6: SUPPORTED    H7: SUPPORTED    H8: SUPPORTED
  H9: SUPPORTED    H10: SUPPORTED   H11: REJECTED    H12: SUPPORTED
  H13: SUPPORTED   H14: SUPPORTED
```

Exit code **0**. Test suite: **310 passed, 0 failed, 0 errors**. Fault
matrix: **40 PASS, 0 FAIL, 0 NOT_TESTED**. `make replay DECISION_ID=<a
real V1-era decision>` reconstructs the original evidence/contract
versions and reaches `status: PASS` (`evidence_hash_match`/
`gate_result_match`/`action_input_match` all `true`, `authz_replay_mode:
live`).

**H11 (the ontology thesis's own central claim — "does the operational
ontology produce measurable benefit over a simpler baseline?") is
REJECTED, honestly, on real evidence**: correctness (500/500 W7 decisions
match) and forensic completeness were at PARITY; replay-across-evolution
outcome was at PARITY (both variants replayed their own real V1/V2-era
history cleanly, same run); the relational baseline was AHEAD on change
effort (zero baseline-specific code for either contract evolution step),
ingestion latency, and infrastructure complexity. The one dimension that
looked like an ontology-specific advantage in an earlier check (SHACL
catching a structural-cardinality mutation the baseline "has no
equivalent for") turned out to be PARITY once tested LIKE-FOR-LIKE: a
live probe (`scripts/probe_baseline_structural_mutation.py`) applied the
literal baseline analogue of that same mutation (dropping the `NOT NULL`
constraint on `decisions.evidence_snapshot`) and found the baseline's own
Postgres constraint rejects the corrupting write at write time exactly
like SHACL does, AND its replay mechanism independently catches the
corruption via hash mismatch even after the constraint is removed. Per
spec 10's own explicitly sanctioned outcome: **"operational ontology is
not necessary for this bounded domain."** Every other hypothesis (H1-H10,
H12-H14 — decision-as-data completeness, gates preventing invalid
effects, closed-loop truth, durable actions, concurrency invariants,
hot-path latency, replay across evolution, controlled ontology evolution,
agent boundedness, deterministic-without-AI, divergence detection,
queryable provenance, and open/closed semantic coexistence) is SUPPORTED
on real, live-measured evidence — full per-hypothesis evidence pointers
and notes are in `experiments/exp-003/results/hypothesis-results.json`
and `final-report.md`.

### Running the definition-of-done sequence from scratch

```bash
cp .env.example .env
export DOCKER_CONFIG=...      # see docs/experiment/briefs/common.md if docker-credential-desktop hangs on macOS
make down && docker compose down -v   # clean machine
make up                        # fresh stack — auto-advances to the current contracts
SEED=42 make seed
make test                      # 187 passed, 0 failed (model/experiment/contracts/component/integration)
make experiment                # creates a new experiments/exp-NNN/ — see above; takes ~1.5-2.5h
make replay DECISION_ID=<a V1-era decision id from exp-NNN/results/historical-corpus.json>
make report                    # regenerates exp-NNN/results/final-report.md, no re-run
```

`make experiment` performs its OWN internal destructive reset partway
through (the evolution comparison, item 7 above) — this is intentional:
`make experiment` "by definition creates a fresh, self-contained
experiment," so its results never depend on whatever `make test` happened
to create on the outer, DoD-validating stack.

### Real bugs found and fixed while building this phase (disclosed, not hidden)

- **Projection-builder race in the auto-advance path**: `wait-converged`
  proves Kafka CDC lag is 0, not that `services/projection_builder`'s own
  ~3s-interval live poll loop has finished rebuilding every row from the
  now-fully-ingested graph — `migrations/v1_to_v2/deploy.py`'s own
  before/after projection-hash check could catch a moving target right
  after a fresh seed. Fixed by quiescing (`build_all()` in a loop until
  two consecutive rebuilds hash-match) before `deploy-v2` runs.
- **A wrong, since-reverted attempt at item 7**: an early version of the
  evolution comparison tried to fake the "V1 genesis" state by flipping
  only the `deployed_version.json` pointer without reloading RDF4J's live
  SHACL shapes, reasoning a v1-labeled write would only ever be validated
  against a strictly more permissive v3 ruleset. That reasoning was
  backwards (a more permissive ruleset accepts MORE, so it doesn't prove
  v1 rules were satisfied) and was replaced with a real, self-contained
  fresh reset that keeps the genuine V1 shapes live while V1-era history
  is built.
- **F27 test race**: `services/projection_builder`'s live poll loop could
  heal a tampered row between a test's UPDATE and its consistency check.
  Fixed by holding the same `pg_advisory_lock` key `build_all()` itself
  takes across the whole tamper → check → restore window; proven
  deterministic with a new 20x-under-load test.
- **Four derivation-logic bugs found by independent review** (H2 scoped
  to the wrong fault set; H14 checking keys that don't exist in this
  repo; the hot-read-p95 acceptance item reading the wrong JSON path; H11
  crediting an ontology advantage without a like-for-like check) **plus a
  fifth (H6 duplicating the same hot-read-p95 bug in a second, divergent
  implementation) and a project-wide sweep for the same "no evidence
  silently reads as a verdict" pattern** — all fixed, all now covered by
  `tests/experiment/test_verdict_derivation.py` (61 tests, every
  hypothesis/acceptance-item/exit-code rule tested against both a
  known-positive and a known-negative fixture).
- **`git log --follow` silently failing on multi-path queries**: used for
  H11's git-derived migration-effort numbers; `--follow` only accepts
  exactly one pathspec and errors on a second, which went unnoticed
  because the subprocess return code wasn't checked — a real "0 files
  changed" is indistinguishable from a failed git call unless you check.

See `docs/experiment/implementation-notes.md`'s Phase 10b section for the
full write-up, including every intermediate experiment (exp-001, exp-002)
kept as committed, immutable records of what each review round actually
found.

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
