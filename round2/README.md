# EOO Round 2 v2 — Palantir-Class Hypothesis-Driven Development Pack

**Goal:** test whether an open-source system can realize an **Executable Operational Ontology of Palantir class** without assuming a particular semantic storage technology.

This pack is a research contract, not an architecture sales document.

> **Status of the earlier Round 2 draft:** it was never executed and produced no evidence. This pack **replaces it before execution**. Do not run both packs. The identifiers H15–H22 are intentionally reused here because no experimental record exists under the abandoned draft. Historical draft hypotheses are namespaced as `R2-draft/H15` … `R2-draft/H22`; see [`history/SUPERSESSION.md`](history/SUPERSESSION.md).

## Target definition

For this round, "Palantir-class" means the capability matrix:

```text
                    Data        Logic       Action       Security
Language              ✓            ✓            ✓            ✓
Engine                ✓            ✓            ✓            ✓
Toolchain             ✓            ✓            ✓            ✓
```

or, compactly:

```text
(Language × Engine × Toolchain) over (Data × Logic × Action × Security)
```

This definition follows Palantir's current public architecture description, but the experiment tests an open-source behavioral architecture, **not product parity with Foundry/AIP**.

## Fixed decisions entering Round 2 v2

1. EOO is **backend-neutral**. RDF is optional, not definitional.
2. A first-class **Ontology Language** must exist.
3. **OpenPona is the first candidate**, not the assumed winner.
4. `Function != Action` is a hard semantic/runtime distinction.
5. The primary scale axis is **semantic variety**, not row count.
6. Domain 1 is the existing manufacturing POC.
7. Domain 2 is the **operational-ontology-poc project itself**.
8. Both domains must use the same meta-model/kernel/runtime.
9. A domain may add object types, links, functions, actions, policies and adapters; adding kernel primitives or runtime branches counts as evidence against generality.
10. For Project Ontology, **Git is canonical authority** in the first experiment.
11. Project Ontology uses the strong model: Hypothesis, Rival, Prediction, Falsifier, Experiment, Metric, Threshold, Evidence, Verdict, Component, ContractVersion, Commit, Test, Decision and Failure.
12. There is no "weak executable" phase. We target governed execution immediately.

## Why this round exists

The existing POC already demonstrated a strong governed operational loop. In `exp-003`, H1-H10 and H12-H14 were supported, while H11 — "the ontology produces measurable benefit over a simpler baseline" — was **rejected** in the bounded manufacturing domain. The relational baseline reached parity on correctness/replay/forensics and was cheaper on several operational dimensions.

Round 2 v2 therefore attacks a different claim:

> Does an Ontology Language + shared Engine + generated Toolchain begin to earn its cost when **semantic variety and cross-domain reuse** increase?

If the answer remains no, the project should narrow or abandon the separate ontology-layer thesis rather than add more machinery.

## Hypotheses

| ID | Question |
|---|---|
| H15 | Can OpenPona be a lossless Ontology Language surface over a backend-neutral typed IR? |
| H16 | Can Manufacturing + Project Ontology share a bounded language/kernel without new primitives? |
| H17 | Can the Engine enforce `Function != Action` as a hard capability/effect boundary? |
| H18 | Can Project Ontology govern its own hypothesis-driven lifecycle and outperform file-only discipline on invariant enforcement? |
| H19 | Can Git remain canonical while the ontology is executable, rebuildable and concurrency-safe? |
| H20 | Can one generic Engine execute both domains with zero domain-specific runtime branches? |
| H21 | Can one Toolchain generate typed/query/action/agent surfaces with security equivalence across both domains? |
| H22 | As real domains accumulate, do semantic-variety adaptation gains repay ontology-specific tax? |

H22 is deliberately **not eligible for strong support with only two domains**. Its preregistered minimum is three independently useful real domains.

## Execution order

The pack uses a kill-chain rather than a feature roadmap:

```text
H15 OpenPona language
  ↓ survives
H16 bounded kernel
  ↓ survives
H17 effect boundary
  ↓ survives
H18 self-hosted Project Ontology
  ↓ survives
H19 Git authority / rebuild
  ↓ survives
H20 generic Engine
  ↓ survives
H21 generated Toolchain
  ↓ accumulates real domains
H22 break-even / semantic-variety trend
```

A rejected hypothesis narrows or stops downstream work unless a new version explicitly changes the thesis.

## Agent posture

Read [`AGENTS.md`](AGENTS.md) before implementation. The short form:

```text
observation
→ hypothesis
→ strongest rival
→ discriminating prediction
→ falsifier
→ independent oracle
→ smallest killing experiment
→ evidence
→ frozen evaluator
→ verdict
→ only then architecture expansion
```

**Green code is not a scientific verdict.**

## Python Hypothesis policy

Property-based/state-machine testing is the default when the falsifier has a computable oracle. It must not be used to replace an architectural or real-world claim with a convenient unit-test surrogate.

Read [`docs/09_python_hypothesis_strategy.md`](docs/09_python_hypothesis_strategy.md).

## Before execution

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
make check
make test
# review REVIEW_CHECKLIST.md
make freeze
```

`make freeze` intentionally refuses to freeze the protocol if Python `hypothesis` is unavailable; property/state-machine tests must not be silently skipped at preregistration time.
