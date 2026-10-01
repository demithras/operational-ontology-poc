# H21 — The Toolchain can be generated from the ontology contract with security equivalence

## Claim

From the shared Ontology Language/IR, the system can generate typed object/query/function/action/agent surfaces for both domains so that new ordinary domain resources require no handwritten endpoint and expose exactly the capabilities allowed by the security model.

## Strong null/rival

A useful developer/agent surface still requires bespoke endpoints and permission glue per domain; the ontology is not functioning as a backend/toolchain contract.

## Why this exists

Typed resource definitions contain enough shape/capability/security metadata to derive SDK types, query operations and governed Action tools mechanically.

## Primary falsifiers

- A normal domain object/action needs a handwritten endpoint to become usable.
- Generated surface exposes a capability denied by the authority oracle.
- Generated surface hides an allowed capability because permission logic is duplicated incorrectly.
- Interface polymorphism requires per-concrete-type tool code.

## Python Hypothesis role

Generate schemas, principals, resource sets, capabilities and agent requests; differential-test generated surface against independent type/security oracles.

## Stop rule

- If ordinary resources repeatedly require handwritten endpoints, reject Toolchain-generation claim before building UI/convenience layers.
