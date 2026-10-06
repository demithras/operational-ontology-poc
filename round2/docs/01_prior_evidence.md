# 01 — Prior evidence and why Round 2 v2 replaces the unexecuted draft

## Existing POC result

The current `operational-ontology-poc` implements a substantial governed operational loop over a synthetic manufacturing domain: CDC ingestion, identity resolution, semantic core, projections, authorization, policy, decision-as-data, durable actions, outcome observation, reconciliation, replay/versioning, agent surface, fault injection and differential testing.

The final `exp-003` report recorded:

```text
H1-H10: supported
H11:    rejected
H12-H14:supported
310 tests passed
40/40 fault cases passed
```

The important result is H11. The relational baseline reached parity on tested decision correctness, replay and forensic completeness while avoiding several ontology-specific costs. Therefore this research may not treat semantic sophistication, RDF, or a graph store as value in themselves.

## The first Round 2 draft was never executed

Two earlier Round 2 specification ZIPs were designed around eight hypotheses about blind semantic evolution, heterogeneous integration, agent tooling, cross-domain discovery/policy, source-schema churn, complexity trend and ontology tax. **Neither pack was run. No thresholds were frozen against observed results and no evidence/verdict belongs to those hypotheses.**

After that draft was written, the target changed materially:

- EOO became explicitly backend-neutral;
- `Ontology Language` became a required first-class layer;
- the target became `Language × Engine × Toolchain` over `Data × Logic × Action × Security`;
- `Function != Action` became a hard boundary;
- OpenPona became a falsifiable candidate for Ontology Language;
- the POC project itself became the second real domain;
- Git became canonical authority for that Project Ontology experiment.

Running the old draft first would therefore answer a weaker and partly obsolete question. Round 2 v2 supersedes it **before execution**.

## What was retained from the abandoned draft

Its useful pressure is not discarded. It is migrated into the replacement protocol, primarily H21/H22 and the semantic-variety corpus:

- unforeseen semantic evolution / marginal change cost → H22;
- heterogeneous integration scaling → H22;
- agent task-specific tooling burden → H21 + H22;
- novel cross-domain discovery/query → H21 + H22;
- novel policy composition → H21 + H22;
- source-schema churn isolation → H22;
- advantage-vs-semantic-complexity trend → H22;
- adaptation gains vs ontology tax → H22.

H15–H21 now establish the missing Palantir-class prerequisites before H22 is allowed to make a value/generalization claim. Historical identifiers from the abandoned draft are written as `R2-draft/H15` … `R2-draft/H22` to avoid confusing them with the executable hypotheses in this pack.
