# Sources

Accessed 2026-09-23 unless otherwise noted.

## Source thesis

### Video transcript

*A $250B Lesson: Your Ontology is Missing One Thing* — The Semantic Owl  
Transcript mirror:  
https://youtubetotranscript.com/transcript?v=b7prlnQhQQs

Key sections used:
- operational loops rather than static reporting;
- decision as first-class data with actor/evidence/policy/outcome/time;
- SHACL-style gates and hot-path/deeper-validation tradeoff;
- materialized/hot-path views;
- versioned ontology contracts, migrations, replay;
- the test of live defensible decisions plus later auditability.

The POC treats the video as a hypothesis source, not an authority.

## Palantir benchmark behavior

Palantir Foundry — Action Types Overview:  
https://www.palantir.com/docs/foundry/action-types/overview

Relevant behavior:
- action types define grouped ontology changes;
- actions can include side effects.

Palantir Foundry — Action Log:  
https://www.palantir.com/docs/foundry/action-types/action-log

Relevant behavior:
- successful action submissions can be modeled as ontology objects;
- logs capture action type/version, user, timestamp, edited objects, and related context.

These sources are used only to understand the benchmark pattern, not to assert product parity.

## RDF / validation / provenance

W3C SHACL Recommendation:  
https://www.w3.org/TR/shacl/

Eclipse RDF4J — Validation with SHACL:  
https://rdf4j.org/documentation/programming/shacl/

W3C PROV-O:  
https://www.w3.org/TR/prov-o/

## Authorization and policy

OpenFGA — Authorization for Agents:  
https://openfga.dev/docs/modeling/agents

OpenFGA — Agents as Principals:  
https://openfga.dev/docs/modeling/agents/agents-as-principals

OpenFGA — MCP Server Authorization:  
https://openfga.dev/docs/modeling/agents/mcp-authorization

OpenFGA — Testing Models:  
https://openfga.dev/docs/modeling/testing

Open Policy Agent:  
https://www.openpolicyagent.org/docs

OPA — Policy Testing:  
https://www.openpolicyagent.org/docs/policy-testing

## Durable execution / feedback

Temporal documentation:  
https://docs.temporal.io/

Debezium PostgreSQL connector:  
https://debezium.io/documentation/reference/stable/connectors/postgresql.html

Apache Kafka introduction:  
https://kafka.apache.org/intro/

## Testing

Hypothesis — Stateful Testing:  
https://hypothesis.readthedocs.io/en/latest/stateful.html

## Source discipline

All POC-specific latency thresholds, domain rules, dataset sizes, acceptance criteria, and architecture decisions in this package are **experiment design choices**, not claims attributed to the sources above.
