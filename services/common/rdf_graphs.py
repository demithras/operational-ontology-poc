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

from services.common.iri import safe_iri_component

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
    # decision_id is normally server-generated (f"D-{uuid4().hex[:20]}",
    # services/decision_service/propose_flow.py) and IRIREF-safe by
    # construction, but percent-encoded anyway (services/common/iri.py) —
    # defense-in-depth costs nothing here and this function has no way to
    # know a future caller won't pass something else through.
    return f"{DECISIONS_GRAPH_PREFIX}{safe_iri_component(decision_id)}"


# Entity IRI scheme shared with services/ingestion (implementation-notes.md
# Phase 3: "Entity IRI scheme: https://example.local/factory/instance/{ClassName}/{localId}").
FACTORY_INSTANCE_BASE = "https://example.local/factory/instance/"


def fac_instance_iri(class_name: str, local_id: str) -> str:
    # local_id here is frequently RAW SOURCE-DATABASE DATA (a WMS
    # warehouse_id/lot_id, an ERP/MES primary key) with no charset
    # constraint at the schema level — see services/common/iri.py's module
    # docstring (F37/F38: a direct manual DB edit or a poison CDC row could
    # otherwise inject SPARQL via a crafted id landing unescaped inside
    # `<...>`). class_name is always a hardcoded literal from this
    # codebase's own source, never external data — left unencoded so the
    # resulting IRI stays exactly the well-known, documented scheme.
    return f"{FACTORY_INSTANCE_BASE}{class_name}/{safe_iri_component(local_id)}"


# oo: instance IRI scheme for governance objects (decisions, evidence
# snapshots, actors, gate-result resources) — distinct namespace from the
# fac: domain-entity instances above.
OO_INSTANCE_BASE = "https://example.local/oo/instance/"


def oo_instance_iri(class_name: str, local_id: str) -> str:
    # Same rationale as fac_instance_iri above — local_id here includes
    # actor ids (services/decision_service/rdf_writer.py's approved_by,
    # services/common/action_rdf.py's executed_by_actor_id) that are NOT
    # always the strictly-validated propose()/approve() request fields
    # (an approver_id IS validated by schemas.py's _ID_PATTERN today, but
    # this function has no way to enforce that stays true at every future
    # call site, and action_execution_id/decision_id-derived local_ids
    # passed through here are cheap to protect regardless).
    return f"{OO_INSTANCE_BASE}{class_name}/{safe_iri_component(local_id)}"
