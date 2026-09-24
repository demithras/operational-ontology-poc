"""Reverse identity lookup: canonical part id -> a SPECIFIC source system's
own local id (contracts/identity/v1/mapping_rules.yaml,
services/identity_resolver, oo:IdentityMapping — services/ingestion/store.py).

Needed because `propose()`'s `parameters.part` is always CANONICAL-id-typed
(contracts/actions/v1/transfer_inventory.yaml), but the external system
services/action_worker actually calls (WMS's `POST /transfers`) only knows
its OWN local part id (e.g. `SKU-88429`, never `PX-17`) — WMS never learns
canonical ids at all (services/wms owns no identity-resolution concept, per
docs/experiment/spec/02_scope_and_non_goals.md's per-system credential/
identity isolation). Forward resolution (source-local -> canonical) happens
once, at CDC ingestion time; this is the one place Phase 6 needs it in
reverse, at EXECUTION time, to build a request WMS can actually act on.
"""

from __future__ import annotations

from services.common.sparql_escape import escape_sparql_literal

OO_PREFIX = "PREFIX oo: <https://example.local/oo/>"


def resolve_canonical_part_to_source_local(rdf4j_client, canonical_part_id: str, system: str) -> str | None:
    canonical_iri = f"https://example.local/factory/instance/Part/{escape_sparql_literal(canonical_part_id)}"
    safe_system = escape_sparql_literal(system)
    query = f"""
{OO_PREFIX}
SELECT ?sourceLocalId WHERE {{
  ?mapping a oo:IdentityMapping ;
           oo:sourceSystem "{safe_system}" ;
           oo:canonicalId <{canonical_iri}> ;
           oo:sourceLocalId ?sourceLocalId .
}}
LIMIT 1
"""
    rows = rdf4j_client.select(query)
    return rows[0]["sourceLocalId"] if rows else None
