"""RDF writes for oo:ActionExecution / oo:Outcome (Phase 6) — shared by
services/action_worker (the executing side) and services/reconciliation
(the independent-reality-check side, H12), so both write the SAME shape
into the SAME per-decision graph the Decision itself already lives in
(services/common/rdf_graphs.py::decision_graph_iri — spec 03's "Decision
provenance links evidence -> decision -> action -> observed outcome", one
self-contained record per decision, matching Phase 5's own design rather
than a second parallel graph namespace).

Exactly TWO writes per ActionExecution, both idempotent-safe to replay
(Temporal may re-run an activity after a worker crash before its result was
recorded — F12/F13):

1. `write_execution_started` — the ONLY write before the external call.
   Adds the ActionExecution resource (additive; RDF is a set, so replaying
   with identical values is a no-op) and flips Decision.status
   APPROVED -> EXECUTING via one atomic DELETE/INSERT (a replay's DELETE
   simply matches nothing the second time, and the INSERT re-asserts an
   already-true triple — both safe no-ops).
2. `write_execution_finalized` — the ONLY write after the outcome is known
   (either a real CDC-correlated observation or a definitive timeout/
   failure). Adds commandStatus/commandReceiptJson/completedAt (first and
   only time these predicates are ever set) plus the Outcome resource, and
   flips Decision.status EXECUTING -> the terminal status, same
   replay-safe DELETE/INSERT pattern.

Every free-text literal (JSON blobs, raw command-response strings) is
escaped via services/common/sparql_escape.py — defense in depth per the
F31 policy already established in services/decision_service/rdf_writer.py,
even though these values are server-derived rather than directly
caller-controlled (a WMS error message can still legitimately contain a
quote character).
"""

from __future__ import annotations

import json
from datetime import datetime

from services.common.decision_status import status_concept_iri
from services.common.rdf_graphs import decision_graph_iri, fac_instance_iri, oo_instance_iri
from services.common.sparql_escape import escape_sparql_literal

OO = "https://example.local/oo/"
PROV = "http://www.w3.org/ns/prov#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _dt(value: datetime) -> str:
    return value.isoformat()


def json_for_rdf(obj) -> str:
    """JSON serialization for values headed into a SPARQL UPDATE string
    literal — deliberately `ensure_ascii=False`, unlike
    services/decision_service/hashing.py::canonical_json (which MUST stay
    ensure_ascii=True/stable for hash reproducibility and is not used
    here). Found empirically: RDF4J's SPARQL grammar for a `Modify`
    template's (DELETE/INSERT ... WHERE) string literals does NOT tolerate
    json.dumps's default `\\uXXXX` escapes the same way an `INSERT DATA`
    block's QuadData literals do — a `\\u2014` em-dash escape from a WMS
    fault-injection message ('...— never persisted') 400'd with
    'MALFORMED QUERY: Invalid escape sequence' only inside the combined
    DELETE/INSERT form this module's write_* functions all use. Emitting
    the real UTF-8 character instead (still passed through
    escape_sparql_literal for the SPARQL-reserved characters) avoids the
    ambiguity entirely."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def write_execution_started(
    rdf4j_client,
    decision_id: str,
    action_execution_id: str,
    external_system: str,
    external_operation: str,
    temporal_workflow_id: str,
    started_at: datetime,
    from_status: str = "APPROVED",
    quantity: int | None = None,
    source_warehouse: str | None = None,
    destination_warehouse: str | None = None,
) -> tuple[bool, str]:
    graph = decision_graph_iri(decision_id)
    decision_iri = oo_instance_iri("Decision", decision_id)
    ae_iri = oo_instance_iri("ActionExecution", action_execution_id)
    old_status = status_concept_iri(from_status)
    new_status = status_concept_iri("EXECUTING")

    # oo:quantity/oo:sourceWarehouse/oo:destinationWarehouse are OPTIONAL on
    # oo:ActionExecution (contracts/shapes/v1/action-execution-shape.ttl's
    # Phase 6 generalization) — only transfer_inventory supplies them.
    transfer_fields = ""
    if quantity is not None:
        transfer_fields += f'\n    oo:quantity "{int(quantity)}"^^xsd:integer ;'
    if source_warehouse is not None:
        source_iri = fac_instance_iri("Warehouse", escape_sparql_literal(source_warehouse))
        transfer_fields += f"\n    oo:sourceWarehouse <{source_iri}> ;"
    if destination_warehouse is not None:
        dest_iri = fac_instance_iri("Warehouse", escape_sparql_literal(destination_warehouse))
        transfer_fields += f"\n    oo:destinationWarehouse <{dest_iri}> ;"

    sparql = f"""
PREFIX oo: <{OO}>
PREFIX xsd: <{XSD}>
DELETE {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status <{old_status}> }} }}
INSERT {{ GRAPH <{graph}> {{
  <{decision_iri}> oo:status <{new_status}> ;
    oo:actionExecution <{ae_iri}> .
  <{ae_iri}> a oo:ActionExecution ;
    oo:actionExecutionId "{escape_sparql_literal(action_execution_id)}" ;
    oo:externalSystem "{escape_sparql_literal(external_system)}" ;
    oo:externalOperation "{escape_sparql_literal(external_operation)}" ;
    oo:temporalWorkflowId "{escape_sparql_literal(temporal_workflow_id)}" ;{transfer_fields}
    oo:startedAt "{_dt(started_at)}"^^xsd:dateTime .
}} }}
WHERE {{}}
"""
    resp = rdf4j_client.update(sparql)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text


def write_execution_finalized(
    rdf4j_client,
    decision_id: str,
    action_execution_id: str,
    executed_by_actor_id: str,
    final_status: str,
    command_status: str,
    command_receipt_json: str,
    completed_at: datetime,
    outcome_id: str,
    reconciliation_state: str,
    expected_effect_json: str,
    observed_effect_json: str,
    observed_at: datetime,
    compensation_status: str,
    source_evidence_lsn: str | None,
    compensating_action_execution_id: str | None = None,
    from_status: str = "EXECUTING",
) -> tuple[bool, str]:
    graph = decision_graph_iri(decision_id)
    decision_iri = oo_instance_iri("Decision", decision_id)
    ae_iri = oo_instance_iri("ActionExecution", action_execution_id)
    outcome_iri = oo_instance_iri("Outcome", outcome_id)
    executor_iri = oo_instance_iri("HumanActor", escape_sparql_literal(executed_by_actor_id))
    old_status = status_concept_iri(from_status)
    new_status = status_concept_iri(final_status)

    extra_outcome_triples = ""
    if source_evidence_lsn:
        extra_outcome_triples += f'\n  <{outcome_iri}> oo:sourceEvidenceLsn "{escape_sparql_literal(source_evidence_lsn)}" .'
    if compensating_action_execution_id:
        extra_outcome_triples += (
            f'\n  <{outcome_iri}> oo:compensatingActionExecutionId "{escape_sparql_literal(compensating_action_execution_id)}" .'
        )

    sparql = f"""
PREFIX oo: <{OO}>
PREFIX prov: <{PROV}>
PREFIX xsd: <{XSD}>
DELETE {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status <{old_status}> }} }}
INSERT {{ GRAPH <{graph}> {{
  <{decision_iri}> oo:status <{new_status}> ;
    oo:executedBy <{executor_iri}> .
  <{executor_iri}> a oo:HumanActor, prov:Agent ; oo:actorId "{escape_sparql_literal(executed_by_actor_id)}" .
  <{ae_iri}> oo:commandStatus "{escape_sparql_literal(command_status)}" ;
    oo:commandReceiptJson "{escape_sparql_literal(command_receipt_json)}" ;
    oo:completedAt "{_dt(completed_at)}"^^xsd:dateTime ;
    oo:outcome <{outcome_iri}> .
  <{outcome_iri}> a oo:Outcome ;
    oo:outcomeId "{escape_sparql_literal(outcome_id)}" ;
    oo:reconciliationState "{escape_sparql_literal(reconciliation_state)}" ;
    oo:expectedEffectJson "{escape_sparql_literal(expected_effect_json)}" ;
    oo:observedEffectJson "{escape_sparql_literal(observed_effect_json)}" ;
    oo:observedAtOutcome "{_dt(observed_at)}"^^xsd:dateTime ;
    oo:compensationStatus "{escape_sparql_literal(compensation_status)}" .
  <{outcome_iri}> prov:wasGeneratedBy <{ae_iri}> .{extra_outcome_triples}
}} }}
WHERE {{}}
"""
    resp = rdf4j_client.update(sparql)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text


def write_action_version_invalidated(
    rdf4j_client,
    decision_id: str,
    pinned_sha256: str,
    current_sha256: str,
    detected_at: datetime,
    from_status: str = "APPROVED",
) -> tuple[bool, str]:
    """F34: contracts/actions/v1/<name>.yaml changed after this decision was
    APPROVED (oo:actionPinnedSha256, stamped at propose() time, no longer
    matches a FRESH on-disk hash) — services/action_worker/activities.py::
    verify_and_start_execution calls this INSTEAD of ever writing
    oo:ActionExecution/calling the external system. No ActionExecution/
    Outcome resource is created (nothing was executed); this is a pure
    Decision-status transition, same replay-safe DELETE/INSERT pattern as
    write_execution_started/write_execution_finalized above."""
    graph = decision_graph_iri(decision_id)
    decision_iri = oo_instance_iri("Decision", decision_id)
    old_status = status_concept_iri(from_status)
    new_status = status_concept_iri("ACTION_VERSION_INVALIDATED")

    sparql = f"""
PREFIX oo: <{OO}>
PREFIX xsd: <{XSD}>
DELETE {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status <{old_status}> }} }}
INSERT {{ GRAPH <{graph}> {{
  <{decision_iri}> oo:status <{new_status}> ;
    oo:actionSha256AtExecute "{escape_sparql_literal(current_sha256)}" ;
    oo:actionVersionInvalidatedAt "{_dt(detected_at)}"^^xsd:dateTime .
}} }}
WHERE {{}}
"""
    resp = rdf4j_client.update(sparql)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text


def write_reconciliation_state_update(
    rdf4j_client,
    decision_id: str,
    outcome_id: str,
    old_reconciliation_state: str,
    new_reconciliation_state: str,
    decision_final_status: str | None = None,
    decision_from_status: str | None = None,
) -> tuple[bool, str]:
    """services/reconciliation's own later update to an EXISTING Outcome's
    oo:reconciliationState (e.g. AWAITING_OBSERVATION -> CONVERGED once a
    delayed CDC event finally arrives, F18) — and, when the Decision's own
    status needs to move too (e.g. OUTCOME_UNKNOWN -> OBSERVED_SUCCESS),
    the SAME atomic-retract pattern as write_execution_finalized."""
    graph = decision_graph_iri(decision_id)
    outcome_iri = oo_instance_iri("Outcome", outcome_id)
    decision_iri = oo_instance_iri("Decision", decision_id)
    status_block = ""
    if decision_final_status and decision_from_status:
        old_status = status_concept_iri(decision_from_status)
        new_status = status_concept_iri(decision_final_status)
        status_block = f"""
DELETE {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status <{old_status}> }} }}
INSERT {{ GRAPH <{graph}> {{ <{decision_iri}> oo:status <{new_status}> }} }}
WHERE {{}} ;
"""
    sparql = f"""
PREFIX oo: <{OO}>
{status_block}
DELETE {{ GRAPH <{graph}> {{ <{outcome_iri}> oo:reconciliationState "{escape_sparql_literal(old_reconciliation_state)}" }} }}
INSERT {{ GRAPH <{graph}> {{ <{outcome_iri}> oo:reconciliationState "{escape_sparql_literal(new_reconciliation_state)}" }} }}
WHERE {{}}
"""
    resp = rdf4j_client.update(sparql)
    if resp.status_code in (200, 204):
        return True, ""
    return False, resp.text
