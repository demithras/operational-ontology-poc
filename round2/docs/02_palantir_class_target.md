# 02 — Operational definition of "Palantir-class"

The experiment uses a public, capability-level definition rather than product imitation.

Palantir's current architecture documentation describes the Ontology as integrating **data, logic, action and security**, implemented as an **Ontology Language, Ontology Engine and Ontology Toolchain**. Public core concepts include object types, properties, link types, action types, functions and interfaces.

Sources used to define the target:

- https://www.palantir.com/docs/foundry/architecture-center/ontology-system
- https://www.palantir.com/docs/foundry/ontology/core-concepts
- https://www.palantir.com/docs/foundry/architecture-center/platforms

## Target matrix

| Layer | Data | Logic | Action | Security |
|---|---|---|---|---|
| Language | typed objects/properties/links | functions/rules/interfaces | action definitions/automations | declared authority/policy surface |
| Engine | reads/subscriptions/materialization | evaluates logic | durable governed writes | runtime enforcement/audit |
| Toolchain | typed query/SDK | function development/testing | generated action tools | capability-aware generated surface |

## Minimum Round 2 v2 interpretation

A layer counts only if it is **derived from or governed by the shared ontology contract**. Hand-writing a second FastAPI endpoint for each new domain does not establish a Toolchain.

The target does not require:

- Foundry UI parity;
- enterprise connector catalog parity;
- Palantir scale or certifications;
- identical internal storage technology;
- use of RDF/OWL.
