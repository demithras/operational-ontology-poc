"""Named-graph IRIs shared by the RDF4J bootstrap script, the CDC ingestion
consumer, and the identity resolver — one place so every writer/reader
agrees on where a given kind of fact lives.

docs/experiment/spec/05_ontology_and_contracts.md "Evidence" requires
observed/inferred/derived/asserted facts to stay distinguishable; phase3.md
item 5 says "per-kind named graphs or an oo:factKind" — this repo uses
BOTH: a per-kind named graph (so a SPARQL FROM/GRAPH clause can cheaply
scope to just one kind) AND an oo:factKind triple on each kind's own
describing resource (oo:Observation, future inference-run/projection-run/
assertion resources), so a fact's kind is still recoverable even if it were
ever copied out of its graph.
"""

from __future__ import annotations

RDF4J_SHACL_SHAPES_GRAPH = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"

ONTOLOGY_GRAPH = "https://example.local/oo/graph/ontology"

# oo:Observed facts: canonical entity state as last reported by CDC.
OBSERVED_GRAPH = "https://example.local/oo/graph/observed"

# oo:Observation / oo:SourcePosition / oo:IdentityMapping /
# oo:QuarantinedIdentity provenance records (services/ingestion,
# services/identity_resolver). Kept separate from OBSERVED_GRAPH so a
# consumer that only wants current business state doesn't have to filter
# out provenance bookkeeping triples.
PROVENANCE_GRAPH = "https://example.local/oo/graph/provenance"

# oo:Inferred / oo:Derived / oo:Asserted are declared in the ontology
# (contracts/ontology/v1/oo-observation.ttl) but have no writer before a
# later phase (inference rules, Phase 4 projections, Phase 9 agents).

# Phase 5: one named graph PER DECISION (spec 14 R5 candidate design #1,
# "named immutable graph per decision") — services/decision_service/
# rdf_writer.py writes the Decision + its EvidenceSnapshot + gate-result
# resources + actor nodes into this one graph in a SINGLE POST, so the
# whole self-contained record either commits atomically (SHACL conforms)
# or nothing does (409, per phase3.md's proven transactional-rejection
# behavior). Immutable by convention: nothing in this codebase ever POSTs a
# second time into an already-committed decision's graph.
DECISIONS_GRAPH_PREFIX = "https://example.local/oo/graph/decisions/"


def decision_graph_iri(decision_id: str) -> str:
    return f"{DECISIONS_GRAPH_PREFIX}{decision_id}"


# Entity IRI scheme shared with services/ingestion (implementation-notes.md
# Phase 3: "Entity IRI scheme: https://example.local/factory/instance/{ClassName}/{localId}").
FACTORY_INSTANCE_BASE = "https://example.local/factory/instance/"


def fac_instance_iri(class_name: str, local_id: str) -> str:
    return f"{FACTORY_INSTANCE_BASE}{class_name}/{local_id}"


# oo: instance IRI scheme for governance objects (decisions, evidence
# snapshots, actors, gate-result resources) — distinct namespace from the
# fac: domain-entity instances above.
OO_INSTANCE_BASE = "https://example.local/oo/instance/"


def oo_instance_iri(class_name: str, local_id: str) -> str:
    return f"{OO_INSTANCE_BASE}{class_name}/{local_id}"
