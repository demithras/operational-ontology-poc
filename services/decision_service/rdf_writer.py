"""Builds the ONE self-contained RDF graph for a governed decision (Decision
+ its EvidenceSnapshot + gate-result resources + actor nodes) and writes it
into RDF4J in a SINGLE transactional POST — docs/experiment/spec/06's
propose() "shacl_result = validate(proposed_mutation); persist result; if
invalid: decision -> INVALID_CONFORMANCE" step.

Uses rdflib to build the graph (not hand-formatted f-string turtle) so
string values — including JSON blobs and any caller-supplied text that
survived services/decision_service/schemas.py's identifier validation, e.g.
reasons/messages — are correctly escaped by rdflib's own Turtle serializer,
never string-interpolated into a query or document (the same class of bug
flagged for evidence.py's SPARQL ASK, this is its RDF-serialization
equivalent).
"""

from __future__ import annotations

from datetime import datetime

import rdflib
from rdflib import RDF, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from services.common.decision_status import status_concept_iri
from services.common.rdf_graphs import decision_graph_iri, fac_instance_iri, oo_instance_iri
from services.common.sparql_escape import escape_sparql_literal
from services.decision_service.hashing import canonical_json
from services.decision_service.models import DecisionRecord

OO = Namespace("https://example.local/oo/")
FAC = Namespace("https://example.local/factory/")


PROV = Namespace("http://www.w3.org/ns/prov#")


def _actor_node(g: rdflib.Graph, actor_type: str, actor_id: str) -> URIRef:
    class_name = "SoftwareAgent" if actor_type == "agent" else "HumanActor"
    node = URIRef(oo_instance_iri(class_name, actor_id))
    g.add((node, RDF.type, OO[class_name]))
    # decision-shape.ttl's oo:actor property requires `sh:class prov:Agent`.
    # oo-core.ttl declares oo:HumanActor/oo:SoftwareAgent as
    # rdfs:subClassOf prov:Agent/prov:SoftwareAgent respectively, but RDF4J's
    # ShaclSail runs NO OWL/RDFS inference (implementation-notes.md Phase 3:
    # "runs no OWL inference") — a bare oo:SoftwareAgent typing is NOT
    # recognized as prov:Agent without an explicit triple. Found empirically
    # (a real 409 on the very first agent-actor decision write): assert
    # prov:Agent directly here rather than relying on any subclass chain.
    g.add((node, RDF.type, PROV.Agent))
    if actor_type == "agent":
        g.add((node, RDF.type, PROV.SoftwareAgent))
    g.add((node, OO.actorId, Literal(actor_id)))
    return node


def build_decision_graph(record: DecisionRecord) -> rdflib.Graph:
    g = rdflib.Graph()
    g.bind("oo", OO)
    g.bind("fac", FAC)

    decision = URIRef(oo_instance_iri("Decision", record.decision_id))
    g.add((decision, RDF.type, OO.Decision))
    g.add((decision, OO.decisionId, Literal(record.decision_id)))
    g.add((decision, OO.decisionType, Literal(record.decision_type)))
    g.add((decision, OO.ontologyVersion, Literal(record.ontology_version)))
    g.add((decision, OO.shapeSetVersion, Literal(record.shape_set_version)))
    g.add((decision, OO.authorizationModelVersion, Literal(record.authorization_model_version)))
    g.add((decision, OO.policyBundleVersion, Literal(record.policy_bundle_version)))
    if record.identity_mapping_version:
        g.add((decision, OO.identityMappingVersion, Literal(record.identity_mapping_version)))
    if record.projection_definition_version:
        g.add((decision, OO.projectionDefinitionVersion, Literal(record.projection_definition_version)))
    if record.reconciliation_predicate_version:
        g.add((decision, OO.reconciliationPredicateVersion, Literal(record.reconciliation_predicate_version)))
    if record.openfga_authorization_model_id:
        g.add((decision, OO.openfgaAuthorizationModelId, Literal(record.openfga_authorization_model_id)))
    g.add((decision, OO.actionType, Literal(record.action_type)))
    g.add((decision, OO.actionVersion, Literal(record.action_version, datatype=XSD.integer)))
    g.add((decision, OO.createdAt, Literal(record.created_at.isoformat(), datatype=XSD.dateTime)))
    # .get(..., fallback) rather than a bare [] lookup: services/decision_service/
    # propose_flow.py's test-mode-only `_poisoned()` hook deliberately sets an
    # unrecognized status string to prove F07/INVALID_CONFORMANCE is reachable
    # through the real HTTP API — that must reach RDF4J as an out-of-enum URI
    # (rejected by decision-shape.ttl's sh:in) rather than crash Python with a
    # KeyError before ever reaching the SHACL gate it is trying to exercise.
    g.add((decision, OO.status, URIRef(status_concept_iri(record.status))))
    g.add((decision, OO.parametersJson, Literal(canonical_json(record.parameters))))
    if record.decision_content_hash:
        g.add((decision, OO.decisionContentHash, Literal(record.decision_content_hash)))
    if record.action_pinned_sha256:
        g.add((decision, OO.actionPinnedSha256, Literal(record.action_pinned_sha256)))

    actor_node = _actor_node(g, record.actor_type, record.actor_id)
    g.add((decision, OO.actor, actor_node))
    g.add((decision, rdflib.URIRef("http://www.w3.org/ns/prov#wasAssociatedWith"), actor_node))
    if record.principal_actor_id:
        principal_node = _actor_node(g, "user", record.principal_actor_id)
        g.add((actor_node, OO.actsOnBehalfOf, principal_node))

    # --- Evidence snapshot ---
    es = URIRef(oo_instance_iri("EvidenceSnapshot", record.evidence_snapshot_id))
    g.add((es, RDF.type, OO.EvidenceSnapshot))
    g.add((decision, OO.evidenceSnapshot, es))
    g.add((decision, rdflib.URIRef("http://www.w3.org/ns/prov#used"), es))
    evidence = record.evidence
    if evidence is not None:
        from services.decision_service.hashing import evidence_snapshot_content_hash

        content_hash = evidence_snapshot_content_hash(
            evidence.facts_used, evidence.source_positions, evidence.projection_row_hashes
        )
        g.add((es, OO.snapshotContentHash, Literal(content_hash)))
        g.add((es, OO.snapshotObservedAt, Literal(evidence.observed_at.isoformat(), datatype=XSD.dateTime)))
        g.add((es, OO.requiredFactsJson, Literal(canonical_json(evidence.facts_used))))
        g.add((es, OO.excludedFactsJson, Literal(canonical_json(evidence.facts_excluded))))
        g.add((es, OO.sourcePositionsJson, Literal(canonical_json(evidence.source_positions))))
        g.add((es, OO.projectionRowHashesJson, Literal(canonical_json(evidence.projection_row_hashes))))

    # --- Gate results ---
    if record.authz_result is not None:
        ac = URIRef(oo_instance_iri("AuthorizationCheck", record.decision_id))
        g.add((ac, RDF.type, OO.AuthorizationCheck))
        g.add((ac, OO.checkRelation, Literal(record.authz_result.relation)))
        g.add((ac, OO.checkObject, Literal(record.authz_result.object)))
        g.add((ac, OO.checkOutcome, Literal(record.authz_result.outcome)))
        g.add((ac, OO.checkedAt, Literal(record.authz_result.checked_at.isoformat(), datatype=XSD.dateTime)))
        if record.authz_result.model_id:
            g.add((ac, OO.checkAuthorizationModelId, Literal(record.authz_result.model_id)))
        g.add((decision, OO.authorizationCheck, ac))

    if record.policy_result is not None:
        pe = URIRef(oo_instance_iri("PolicyEvaluation", record.decision_id))
        g.add((pe, RDF.type, OO.PolicyEvaluation))
        g.add((pe, OO.policyOutcome, Literal(record.policy_result.outcome)))
        g.add((pe, OO.policyReasonsJson, Literal(canonical_json(record.policy_result.reasons))))
        g.add((pe, OO.policyObligationsJson, Literal(canonical_json(record.policy_result.obligations))))
        g.add((pe, OO.policyInputHash, Literal(record.policy_result.input_hash)))
        g.add((pe, OO.policyInputJson, Literal(canonical_json(record.policy_result.input_json))))
        g.add((decision, OO.policyEvaluation, pe))

    if record.conformance_outcome is not None:
        cc = URIRef(oo_instance_iri("ConformanceCheck", record.decision_id))
        g.add((cc, RDF.type, OO.ConformanceCheck))
        g.add((cc, OO.conformanceOutcome, Literal(record.conformance_outcome)))
        g.add((cc, OO.conformanceViolationsJson, Literal(canonical_json(record.conformance_violations))))
        g.add((decision, OO.conformanceCheck, cc))

    if record.approved_by:
        g.add((decision, OO.approvedBy, _actor_node(g, "user", record.approved_by)))
        g.add((decision, OO.approvedAt, Literal(record.approved_at.isoformat(), datatype=XSD.dateTime)))
        g.add((decision, OO.approvalDecisionHash, Literal(record.approval_decision_hash)))
        g.add((decision, OO.approvalScope, Literal(record.approval_scope)))

    # --- Concerns (typed links to the real domain objects, H13 traversal) ---
    source_wh, dest_wh = record.concerns_warehouse_pair
    if source_wh:
        g.add((decision, OO.concernsSourceWarehouse, URIRef(fac_instance_iri("Warehouse", source_wh))))
    if dest_wh:
        g.add((decision, OO.concernsDestinationWarehouse, URIRef(fac_instance_iri("Warehouse", dest_wh))))
    if record.concerns_part:
        g.add((decision, OO.concernsPart, URIRef(fac_instance_iri("Part", record.concerns_part))))
    if record.concerns_work_order:
        g.add((decision, OO.concernsWorkOrder, URIRef(fac_instance_iri("WorkOrder", record.concerns_work_order))))

    return g


def write_decision(rdf4j_client, record: DecisionRecord) -> tuple[bool, str]:
    """Returns (committed, detail). On SHACL rejection, `detail` is RDF4J's
    own ValidationReport text (phase3.md's proven 409-with-report
    behavior) — never a fabricated message."""
    graph = build_decision_graph(record)
    ttl = graph.serialize(format="turtle")
    graph_iri = decision_graph_iri(record.decision_id)
    resp = rdf4j_client.add_turtle(ttl, graph_iri=graph_iri)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text


def record_approval(
    rdf4j_client,
    decision_id: str,
    approved_by: str,
    approved_at: datetime,
    approval_decision_hash: str,
    approval_scope: str,
) -> tuple[bool, str]:
    """Transitions an already-committed REQUIRES_APPROVAL decision to
    APPROVED via one atomic SPARQL UPDATE (RDF4JClient.update — see its
    docstring: verified empirically to stay SHACL-validated, still 409s +
    rolls back on a would-be violation). `approved_by`/`approval_scope` are
    already identifier-validated by services/decision_service/schemas.py's
    ApproveRequest before this is ever called; escaped again here anyway
    (defense-in-depth, same policy as evidence.py's SPARQL ASK) since this
    function builds a query by string interpolation."""
    graph = decision_graph_iri(decision_id)
    decision_iri = oo_instance_iri("Decision", decision_id)
    # oo_instance_iri percent-encodes local_id internally
    # (services/common/iri.py) — escape_sparql_literal is for a DIFFERENT
    # SPARQL grammar production (a quoted string literal) and is the wrong
    # function for this IRIREF position; used correctly below for
    # safe_approver_id/safe_hash/safe_scope, which ARE literal contexts.
    approver_iri = oo_instance_iri("HumanActor", approved_by)
    safe_approver_id = escape_sparql_literal(approved_by)
    safe_hash = escape_sparql_literal(approval_decision_hash)
    safe_scope = escape_sparql_literal(approval_scope)
    sparql = f"""
PREFIX oo: <{OO}>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <{XSD}>
DELETE {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status oo:RequiresApproval }} }}
INSERT {{ GRAPH <{graph}> {{
  <{decision_iri}> oo:status oo:Approved ;
    oo:approvedBy <{approver_iri}> ;
    oo:approvedAt "{approved_at.isoformat()}"^^xsd:dateTime ;
    oo:approvalDecisionHash "{safe_hash}" ;
    oo:approvalScope "{safe_scope}" .
  <{approver_iri}> a oo:HumanActor, prov:Agent ; oo:actorId "{safe_approver_id}" .
}} }}
WHERE {{}}
"""
    resp = rdf4j_client.update(sparql)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text
