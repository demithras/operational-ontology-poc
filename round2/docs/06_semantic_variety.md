# 06 — Semantic variety as the primary scale axis

Round 2 v2 does not primarily ask whether the system handles more rows. It asks whether the same language/kernel/engine/toolchain remains useful as **meanings and operational structures vary**.

## Dimensions

- number of object types;
- number and shape of relation types;
- relation depth and N:M density;
- interface/polymorphism diversity;
- function signatures;
- action/effect models;
- authority models;
- policy shapes;
- source identity models;
- version/evolution patterns;
- novel query shapes;
- cross-domain relations.

## Current domains

```text
D1 = synthetic manufacturing operations
D2 = operational-ontology-poc research project
```

Future D3+ domains should come from real projects after the two-domain model works. H22 is intentionally not allowed to claim a general trend from only D1+D2.

## Adaptation-cost rule

Domain additions may add:

```text
object/link/interface definitions
functions
actions
policies/authority declarations
source adapters
views/application configuration
```

The following count against bounded-kernel generality:

```text
new kernel primitive kinds
new Engine domain branches
new compiler special cases keyed to domain name/type
new handwritten Toolchain endpoints required only because generation is insufficient
```
