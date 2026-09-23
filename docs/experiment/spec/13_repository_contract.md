# 13 — Target Repository Contract

## Repository layout

```text
open-operational-ontology/
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
│
├── contracts/
│   ├── ontology/
│   │   ├── v1/
│   │   ├── v2/
│   │   └── v3/
│   ├── shapes/
│   ├── actions/
│   ├── policies/
│   ├── authorization/
│   ├── projections/
│   └── manifests/
│
├── services/
│   ├── erp/
│   ├── mes/
│   ├── wms/
│   ├── ingestion/
│   ├── identity_resolver/
│   ├── decision_service/
│   ├── projection_builder/
│   ├── action_worker/
│   ├── reconciliation/
│   └── mcp/                 # phase 2
│
├── reference_model/
│   ├── state.py
│   ├── transitions.py
│   └── invariants.py
│
├── migrations/
│   ├── v1_to_v2/
│   └── v2_to_v3/
│
├── seed/
│   ├── generators/
│   └── fixtures/
│
├── tests/
│   ├── model/
│   ├── contracts/
│   ├── component/
│   ├── integration/
│   ├── stateful/
│   ├── faults/
│   ├── replay/
│   ├── performance/
│   ├── ab/
│   └── agent/
│
├── experiments/
│   ├── exp-001/
│   │   ├── manifest.yaml
│   │   ├── seeds.txt
│   │   └── results/
│   └── ...
│
├── observability/
│   └── otel/
│
└── docs/
    ├── adr/
    └── experiment/
```

## Mandatory commands

```bash
make up
make down
make reset
make seed
make test-unit
make test-contracts
make test-integration
make test-stateful
make test-faults
make test-replay
make bench
make experiment
make report
make replay DECISION_ID=<id>
```

`make test` may aggregate all non-performance mandatory tests.

## `make seed`

Must accept deterministic seed:

```bash
SEED=42 make seed
```

Same seed => same business dataset.

## `make experiment`

Creates immutable directory:

```text
experiments/exp-XXX/results/
```

containing:

```text
environment.json
contract-manifest.json
test-results.xml/json
hypothesis-results.json
latency.json
fault-results.json
ab-results.json
traces-reference.txt
final-report.md
```

## Contract manifest

Example:

```json
{
  "ontology": {"version": "3.0.0", "sha256": "..."},
  "shapes": {"version": "15", "sha256": "..."},
  "opa": {"version": "31", "sha256": "..."},
  "openfga": {"version": "8", "sha256": "..."},
  "actions": {
    "transfer_inventory": {"version": 7, "sha256": "..."}
  },
  "code_git_commit": "..."
}
```

## CI gates

Pull request cannot merge if:
- SHACL negative fixture unexpectedly conforms;
- OPA test suite empty/fails;
- OpenFGA model tests fail;
- reference-model tests fail;
- replay fixtures fail;
- migration breaks corpus;
- action schema compatibility check fails without migration declaration.

Nightly/local extended:
- stateful high-example suite;
- full fault matrix;
- performance;
- A/B.

## Architecture Decision Records

Any substitution of a reference component must add ADR:

```text
Context
Decision
Alternatives
Hypotheses affected
Experimental equivalence
Consequences
```

## No hidden manual steps

If the experiment requires clicking a GUI to configure policy/ontology, that configuration must be exported into version-controlled files before the result is considered reproducible.
