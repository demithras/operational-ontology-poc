"""Read-only SPARQL lookups for oo:ActionExecution / oo:Outcome, backing
`GET /executions/{id}` / `GET /outcomes/{id}` (docs/experiment/spec/06's API
surface). No GRAPH clause needed — matches contracts/queries/v1/q*.rq's own
convention (verified working since Phase 5): RDF4J's default query dataset
already spans every named graph this repo ever writes into, so a plain
`SELECT` finds a resource regardless of which per-decision graph
(services/common/rdf_graphs.py::decision_graph_iri) it lives in.
"""

from __future__ import annotations

from services.common.sparql_escape import escape_sparql_literal

OO_PREFIX = "PREFIX oo: <https://example.local/oo/>"


def get_execution(rdf4j_client, action_execution_id: str) -> dict | None:
    safe_id = escape_sparql_literal(action_execution_id)
    query = f"""
{OO_PREFIX}
SELECT ?decisionId ?externalSystem ?externalOperation ?temporalWorkflowId ?commandStatus
       ?commandReceiptJson ?startedAt ?completedAt ?outcomeId WHERE {{
  ?ae oo:actionExecutionId "{safe_id}" .
  ?decision oo:actionExecution ?ae ; oo:decisionId ?decisionId .
  OPTIONAL {{ ?ae oo:externalSystem ?externalSystem }}
  OPTIONAL {{ ?ae oo:externalOperation ?externalOperation }}
  OPTIONAL {{ ?ae oo:temporalWorkflowId ?temporalWorkflowId }}
  OPTIONAL {{ ?ae oo:commandStatus ?commandStatus }}
  OPTIONAL {{ ?ae oo:commandReceiptJson ?commandReceiptJson }}
  OPTIONAL {{ ?ae oo:startedAt ?startedAt }}
  OPTIONAL {{ ?ae oo:completedAt ?completedAt }}
  OPTIONAL {{ ?ae oo:outcome ?outcome . ?outcome oo:outcomeId ?outcomeId }}
}}
"""
    rows = rdf4j_client.select(query)
    if not rows:
        return None
    row = rows[0]
    row["action_execution_id"] = action_execution_id
    return row


def get_outcome(rdf4j_client, outcome_id: str) -> dict | None:
    safe_id = escape_sparql_literal(outcome_id)
    query = f"""
{OO_PREFIX}
SELECT ?reconciliationState ?expectedEffectJson ?observedEffectJson ?observedAtOutcome
       ?compensationStatus ?sourceEvidenceLsn ?compensatingActionExecutionId WHERE {{
  ?outcome oo:outcomeId "{safe_id}" .
  OPTIONAL {{ ?outcome oo:reconciliationState ?reconciliationState }}
  OPTIONAL {{ ?outcome oo:expectedEffectJson ?expectedEffectJson }}
  OPTIONAL {{ ?outcome oo:observedEffectJson ?observedEffectJson }}
  OPTIONAL {{ ?outcome oo:observedAtOutcome ?observedAtOutcome }}
  OPTIONAL {{ ?outcome oo:compensationStatus ?compensationStatus }}
  OPTIONAL {{ ?outcome oo:sourceEvidenceLsn ?sourceEvidenceLsn }}
  OPTIONAL {{ ?outcome oo:compensatingActionExecutionId ?compensatingActionExecutionId }}
}}
"""
    rows = rdf4j_client.select(query)
    if not rows:
        return None
    row = rows[0]
    row["outcome_id"] = outcome_id
    return row
