# 04 — Domain 2: Project Ontology

The second real domain is the `operational-ontology-poc` project itself.

This is not a demo domain. It must govern the actual research lifecycle.

## Required object types

At minimum:

```text
Hypothesis
Rival
Prediction
Falsifier
Experiment
Metric
Threshold
Evidence
Verdict
Component
ContractVersion
Commit
Test
Decision
Failure
```

Additional ordinary domain types may be introduced without changing the kernel if evidence shows they are necessary.

## Required links

Examples:

```text
Hypothesis HAS_RIVAL Rival
Hypothesis PREDICTS Prediction
Hypothesis FALSIFIED_BY Falsifier
Hypothesis TESTED_BY Experiment
Experiment MEASURES Metric
Metric GOVERNED_BY Threshold
Experiment PRODUCES Evidence
Evidence SUPPORTS_OR_REFUTES Hypothesis
Verdict EVALUATES Hypothesis
Evidence CAPTURED_AT Commit
Component EXISTS_FOR Hypothesis
Test VALIDATES Component
Failure DETECTED_BY Test
Decision CHANGES ContractVersion
```

The exact link vocabulary is domain configuration, not kernel vocabulary.

## Required executable lifecycle

```text
DRAFT
→ PREREGISTERED
→ RUNNING
→ EVALUATED
→ SUPPORTED | REJECTED | INCONCLUSIVE | INVALID
→ optionally SUPERSEDED by a new hypothesis/version
```

Hard rules:

- preregistration requires claim, strong rival, predictions, falsifiers, evidence schema and evaluator;
- after `PREREGISTERED`, changing a threshold/falsifier/evaluator creates a new experiment version;
- `RUNNING` requires a freeze hash;
- `EVALUATED` requires required evidence or an explicit `INCONCLUSIVE/INVALID` reason;
- a `SUPPORTED` verdict is machine-derived from frozen evidence/evaluator, not arbitrary user input;
- every authoritative evidence artifact binds to experiment version + commit + environment;
- a component with no link to an active hypothesis is flagged as an orphan, not automatically deleted.

## Baseline

The baseline is ordinary Git + Markdown/JSON + scripts with no Project Ontology semantic runtime. Project Ontology must demonstrate value beyond merely representing the same files as objects.
