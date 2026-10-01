# H16 — A bounded ontology kernel survives two semantically different real domains

## Claim

Manufacturing and Project Ontology can both be expressed using the same frozen meta-model/resource kinds without adding kernel primitive kinds, domain-name compiler special cases, or domain-specific semantic operators.

## Strong null/rival

The apparent kernel is only manufacturing-shaped; adding a research-project domain requires new primitive kinds or special-case semantics.

## Why this exists

A genuinely general operational ontology should separate a small set of resource kinds/capabilities from unbounded domain vocabulary, allowing new domains to add declarations rather than new meta-level machinery.

## Primary falsifiers

- A Project Ontology requirement cannot be represented without adding a new kernel resource kind.
- A compiler semantic branch keyed to the domain is required.
- A concept claimed to be domain configuration actually changes generic runtime semantics.

## Python Hypothesis role

Generate legal resource combinations from both domains and mixed cross-domain references to search generic compiler/validation assumptions.

## Stop rule

- If a new primitive is genuinely required, reject/narrow bounded-kernel claim before adding it; record the proposed primitive for a new hypothesis version.
