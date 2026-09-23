"""RDF4J-backed upsert + provenance for CDC ingestion.

Implements phase3.md item 5's core loop: idempotent-under-duplicate-CDC
(key = source + pk + version), out-of-order resolved by source LSN/version
(never wall clock, F20/F35), one oo:Observation provenance record per
applied Debezium event (also written, with applied=false, for
skipped duplicate/stale events — auditable either way), and
oo:SourcePosition tracking so Phase 5 evidence snapshots can cite exact
source positions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, XSD

from services.common import rdf_graphs
from services.common.rdf4j_client import RDF4JClient
from services.identity_resolver.resolver import Quarantined, Resolved
from services.ingestion.lsn import ordering_key
from services.ingestion.mapping import MappedRow

OO = rdflib.Namespace("https://example.local/oo/")
OO_INST = rdflib.Namespace("https://example.local/oo/instance/")


def position_iri(system: str, table: str, pk: str) -> URIRef:
    return OO_INST[f"pos/{system}/{table}/{pk}"]


def identity_mapping_iri(rule_id: str, system: str, local_id: str) -> URIRef:
    # Deterministic (not random) -> re-writing the same resolution is a
    # true no-op (RDF is a set), never grows unbounded across repeated CDC
    # events referencing the same source id.
    return OO_INST[f"idmap/{rule_id}/{system}/{local_id}"]


def quarantine_iri(system: str, local_id: str) -> URIRef:
    return OO_INST[f"quarantine/{system}/{local_id}"]


class IngestionStore:
    def __init__(self, client: RDF4JClient):
        self.client = client

    def get_position(self, system: str, table: str, pk: str) -> tuple[str | None, int | None] | None:
        iri = position_iri(system, table, pk)
        rows = self.client.select(
            f"""
            SELECT ?lsn ?ver WHERE {{
              GRAPH <{rdf_graphs.PROVENANCE_GRAPH}> {{
                <{iri}> <{OO.lastLsn}> ?lsn .
                OPTIONAL {{ <{iri}> <{OO.lastVersion}> ?ver }}
              }}
            }}
            LIMIT 1
            """
        )
        if not rows:
            return None
        return rows[0].get("lsn"), (int(rows[0]["ver"]) if rows[0].get("ver") is not None else None)

    def _update_position(self, system: str, table: str, pk: str, source_lsn, source_version) -> None:
        iri = position_iri(system, table, pk)
        self.client.delete_subject(str(iri), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
        g = rdflib.Graph()
        g.add((iri, RDF.type, OO.SourcePosition))
        if source_lsn is not None:
            g.add((iri, OO.lastLsn, Literal(str(source_lsn), datatype=XSD.string)))
        if source_version is not None:
            g.add((iri, OO.lastVersion, Literal(int(source_version), datatype=XSD.integer)))
        g.add((iri, OO.lastObservedAt, Literal(_now(), datatype=XSD.dateTime)))
        resp = self.client.add_turtle(g.serialize(format="turtle"), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
        resp.raise_for_status()

    def _write_observation(
        self,
        system: str,
        table: str,
        pk: str,
        op: str,
        source_lsn,
        source_version,
        applied: bool,
        entity_iri: URIRef | None,
    ) -> None:
        obs_iri = OO_INST[f"obs/{system}/{table}/{pk}/{uuid.uuid4()}"]
        g = rdflib.Graph()
        g.add((obs_iri, RDF.type, OO.Observation))
        g.add((obs_iri, OO.factKind, OO.Observed))
        g.add((obs_iri, OO.sourceSystem, Literal(system, datatype=XSD.string)))
        g.add((obs_iri, OO.sourceTable, Literal(table, datatype=XSD.string)))
        g.add((obs_iri, OO.sourcePk, Literal(str(pk), datatype=XSD.string)))
        if source_lsn is not None:
            g.add((obs_iri, OO.sourceLsn, Literal(str(source_lsn), datatype=XSD.string)))
        if source_version is not None:
            g.add((obs_iri, OO.sourceVersion, Literal(int(source_version), datatype=XSD.integer)))
        g.add((obs_iri, OO.cdcOperation, Literal(op, datatype=XSD.string)))
        g.add((obs_iri, OO.observedAt, Literal(_now(), datatype=XSD.dateTime)))
        g.add((obs_iri, OO.applied, Literal(applied)))
        if applied and entity_iri is not None and str(entity_iri):
            g.add((obs_iri, rdflib.namespace.Namespace("http://www.w3.org/ns/prov#").generated, entity_iri))
        resp = self.client.add_turtle(g.serialize(format="turtle"), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
        resp.raise_for_status()

    def _write_identity_record(self, result: Resolved | Quarantined) -> None:
        g = rdflib.Graph()
        if isinstance(result, Resolved):
            iri = identity_mapping_iri(result.rule_id, result.source_system, result.source_local_id)
            self.client.delete_subject(str(iri), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
            g.add((iri, RDF.type, OO.IdentityMapping))
            g.add((iri, OO.mappingRuleId, Literal(result.rule_id, datatype=XSD.string)))
            g.add((iri, OO.mappingRuleVersion, Literal(result.rule_version, datatype=XSD.string)))
            g.add((iri, OO.sourceSystem, Literal(result.source_system, datatype=XSD.string)))
            g.add((iri, OO.sourceLocalId, Literal(result.source_local_id, datatype=XSD.string)))
            g.add((iri, OO.canonicalId, URIRef(f"https://example.local/factory/instance/Part/{result.canonical_id}")))
            g.add((iri, OO.authority, Literal(result.authority, datatype=XSD.string)))
            g.add((iri, OO.confidence, Literal(result.confidence)))
            g.add((iri, OO.createdAtMapping, Literal(result.resolved_at.isoformat(), datatype=XSD.dateTime)))
        else:
            iri = quarantine_iri(result.source_system, result.source_local_id)
            self.client.delete_subject(str(iri), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
            g.add((iri, RDF.type, OO.QuarantinedIdentity))
            g.add((iri, OO.sourceSystem, Literal(result.source_system, datatype=XSD.string)))
            g.add((iri, OO.sourceLocalId, Literal(result.source_local_id, datatype=XSD.string)))
            g.add((iri, OO.quarantineReason, Literal(result.reason, datatype=XSD.string)))
            g.add((iri, OO.createdAtMapping, Literal(result.resolved_at.isoformat(), datatype=XSD.dateTime)))
        resp = self.client.add_turtle(g.serialize(format="turtle"), graph_iri=rdf_graphs.PROVENANCE_GRAPH)
        resp.raise_for_status()

    def apply_event(
        self,
        system: str,
        table: str,
        pk: str,
        op: str,
        entity_iri: URIRef | None,
        mapped: MappedRow | None,
        source_lsn,
        source_version,
    ) -> dict:
        """entity_iri is REQUIRED (even for deletes, where mapped is None)
        — it is what gets retracted from OBSERVED_GRAPH. Pass it via
        services.ingestion.mapping.resolve_entity_iri(), independent of
        whether a full row is available to map."""
        incoming_key = ordering_key(source_lsn, source_version)
        current = self.get_position(system, table, pk)
        if current is not None:
            current_key = ordering_key(current[0], current[1])
            if incoming_key <= current_key:
                self._write_observation(system, table, pk, op, source_lsn, source_version, applied=False, entity_iri=None)
                return {"applied": False, "reason": "stale_or_duplicate"}

        if entity_iri is not None and str(entity_iri):
            self.client.delete_subject(str(entity_iri), graph_iri=rdf_graphs.OBSERVED_GRAPH)

        if op != "d" and mapped is not None and len(mapped.graph) > 0:
            resp = self.client.add_turtle(mapped.graph.serialize(format="turtle"), graph_iri=rdf_graphs.OBSERVED_GRAPH)
            resp.raise_for_status()

        self._update_position(system, table, pk, source_lsn, source_version)
        self._write_observation(system, table, pk, op, source_lsn, source_version, applied=True, entity_iri=entity_iri)

        if mapped is not None and mapped.identity_result is not None:
            self._write_identity_record(mapped.identity_result)

        return {"applied": True, "reason": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
