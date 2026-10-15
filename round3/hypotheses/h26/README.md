# H26 — Knowledge sovereignty holds across supported observable surfaces

## Claim

For protected ontology, operational and provenance knowledge, principals with identical low-authority views cannot distinguish worlds that differ only in data outside their disclosure authority through supported queries, tools, errors, subscriptions, identifiers or provenance surfaces.

## Strong null / rival

Write authorization can be strong while the system still leaks protected knowledge through query shape, object existence, error messages, generated tools, subscriptions or provenance relationships.

## Mechanism under test

Read/disclosure capability is derived from the same versioned authority contract as Actions; generated surfaces omit unauthorized capabilities and the runtime applies uniform redaction/nonexistence semantics over objects, links, provenance and subscriptions.

## Primary falsifiers

- Any protected fact, existence bit or relationship is distinguishable through a frozen supported low-observable channel without disclosure authority.
- A generated schema/tool reveals a hidden capability or protected structural metadata.
- Redaction makes authorized provenance semantically false rather than explicitly partial/redacted.

## Experiment

Differential noninterference experiment over paired worlds that differ only in inaccessible secrets, plus direct exfiltration fuzzing.

1. Freeze disclosure labels, principals, protected facts and the set of low-observable application channels.
2. Generate paired worlds equal on authorized facts and different on protected facts.
3. Execute the same query/tool/error/subscription/provenance observations in each world.
4. Compare canonicalized low outputs and classify any difference against explicit allowed-disclosure rules.
5. Run identifier/existence and schema/tool-discovery attacks.
6. Inject existence-leak, error-detail, hidden-tool and provenance-link mutants.

## Independent oracle

Frozen disclosure lattice plus a canonical low-observation projection that is independent of candidate query/tool implementation.

## Fair baseline

Conventional typed service with row/field-level authorization and response/schema redaction under the same disclosure lattice.

## Stop rule

- If practical disclosure requires a weaker property than application-layer noninterference, reject this claim and preregister the weaker leakage budget explicitly.
