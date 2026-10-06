# H15 — OpenPona can serve as a lossless Ontology Language surface

## Claim

OpenPona can encode every required backend-neutral EOO IR construct for the registered domains and generated valid IR corpus, compile to the independent IR without operational semantic loss, and do so without adding primitive tokens or indispensable semantic sidecars.

## Strong null/rival

OpenPona is useful human/agent notation but is not a sufficient typed Ontology Language; a separate typed DSL or sidecar must carry essential ontology semantics.

## Why this exists

If the 42-token compositional grammar is sufficiently expressive, contextual composition plus explicit grouping/structure should encode the typed distinctions needed by the IR and a compiler should recover them deterministically.

## Primary falsifiers

- Any required frozen IR construct cannot be represented without adding a new primitive token.
- Any required frozen IR construct is recoverable only because indispensable semantics are stored in a non-OpenPona sidecar.
- A valid frozen real-domain contract round-trips to non-equivalent IR.
- Generated counterexample shows Function and Action or authority/cardinality/version semantics collapse under the language.
- The compiler resolves an ambiguous generated input by silently inventing semantics.

## Python Hypothesis role

Recursive strategies generate typed IR packages, cardinalities, interfaces, policies, authority rules, Functions and Actions; round-trip and ambiguity properties search for minimal counterexamples.

## Stop rule

- Reject OpenPona as the core Ontology Language candidate if a frozen required IR kind needs external semantic metadata or a new primitive; continue EOO research with the direct typed DSL rather than rescuing H15 by expanding scope.

## Sidecar boundary

Names and literals are binding data; structure must be in the line. See `experiment.sidecar_classification` in `contract.json` and the matching section in `ontology/semantic-equivalence.md`. OpenPona is pinned at corpus commit `97a9b9e` (v0.2.0).
