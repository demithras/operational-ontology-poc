"""Runs contracts/projections/v1/*.yaml's SPARQL queries against RDF4J and
returns plain Python rows (dicts of str) — the ONLY way
services/projection_builder reads facts (item 1 of
docs/experiment/briefs/phase4.md: "NOT by reading the source DBs").

Entity IRIs are returned by the queries themselves (not joined out to a
separate id literal — see contracts/projections/v1/current_inventory.yaml's
comment on why); `local_id()` extracts the trailing path segment, which is
exactly the local id services/ingestion/mapping.py minted the IRI with
(`https://example.local/factory/instance/{ClassName}/{localId}`).
"""

from __future__ import annotations

from services.common.rdf4j_client import RDF4JClient

PROVENANCE_GRAPH = "https://example.local/oo/graph/provenance"


def local_id(iri: str) -> str:
    return iri.rstrip("/").rsplit("/", 1)[-1]


def run_query(client: RDF4JClient, sparql: str) -> list[dict[str, str]]:
    return client.select(sparql)


def fetch_source_positions(client: RDF4JClient) -> dict[tuple[str, str, str], dict[str, str | None]]:
    """Every oo:SourcePosition currently recorded, indexed by
    (system, table, pk) — the same triple that names each position's own
    IRI (`.../oo/instance/pos/{system}/{table}/{pk}`,
    services/ingestion/store.py::position_iri). One query per build cycle;
    positions are looked up from this in-memory index rather than a
    separate SPARQL round-trip per contributing entity."""
    rows = client.select(
        f"""
        PREFIX oo: <https://example.local/oo/>
        SELECT ?pos ?lsn ?ver ?observedAt WHERE {{
          GRAPH <{PROVENANCE_GRAPH}> {{
            ?pos a oo:SourcePosition ; oo:lastLsn ?lsn .
            OPTIONAL {{ ?pos oo:lastVersion ?ver }}
            OPTIONAL {{ ?pos oo:lastObservedAt ?observedAt }}
          }}
        }}
        """
    )
    index: dict[tuple[str, str, str], dict[str, str | None]] = {}
    for row in rows:
        # pos IRI shape: https://example.local/oo/instance/pos/{system}/{table}/{pk}
        tail = row["pos"].split("/instance/pos/", 1)[-1]
        parts = tail.split("/", 2)
        if len(parts) != 3:
            continue  # defensive: malformed/unexpected IRI shape, skip rather than crash a build cycle
        system, table, pk = parts
        index[(system, table, pk)] = {
            "lsn": row.get("lsn"),
            "version": row.get("ver"),
            "observed_at": row.get("observedAt"),
        }
    return index
