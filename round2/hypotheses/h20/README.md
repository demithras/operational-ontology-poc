# H20 — One generic Engine executes both domains without domain-specific runtime branches

## Claim

The EOO Engine can perform reads, Functions, governed Actions, authority/policy checks, durable execution, observations and provenance for Manufacturing and Project Ontology using generic resource/capability dispatch only.

## Strong null/rival

The shared Engine is superficial; each domain needs hidden special-case branches or bespoke orchestration to execute correctly.

## Why this exists

If operational semantics live in typed resource definitions, contracts and adapters, the Engine should interpret capabilities generically while domain-specific external integrations remain behind declared adapters.

## Primary falsifiers

- A required domain behavior can only be implemented by editing Engine core with a domain-specific branch.
- A domain adapter performs authority/policy/governance semantics that the Engine claims to own.
- A new ordinary action type requires Engine code changes rather than configuration/adapter code.

## Python Hypothesis role

Generate valid generic resources/actions and operation sequences; use instrumentation to assert generic dispatch invariants.

## Stop rule

- If domain-specific Engine branching is required, expose it as plugin architecture and reject the stronger generic-Engine claim.
