"""Declarative table -> RDF mapping for CDC ingestion.

Each source table maps to exactly one fac: class instance, one column per
fac: property, per the authoritative-source-per-property design in
contracts/ontology/v1/fac-core.ttl (structurally enforced here too: each
system's CDC connector only ever carries ITS OWN tables, so no table
mapping can ever write a property another system owns).

Only columns literally named `part` / `part_id` require identity
resolution (services/identity_resolver) — every other id in this domain is
already canonical (docs/experiment/implementation-notes.md Phase 2).

`transfers` (WMS) IS mapped, starting Phase 6 (docs/experiment/implementation-notes.md
Phase 5 section's own handoff note: "wms.transfers CDC topic is still
unmapped into RDF ... Phase 6 is where that mapping needs to land") — to
fac:WmsTransferRecord (contracts/ontology/v1/fac-core.ttl), the CDC-observed
counterpart services/action_worker/services/reconciliation correlate an
oo:ActionExecution's expected effect against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from services.identity_resolver.resolver import IdentityResolver, Quarantined, Resolved

FAC = rdflib.Namespace("https://example.local/factory/")
FAC_INST = rdflib.Namespace("https://example.local/factory/instance/")


def entity_iri(class_name: str, local_id: str) -> URIRef:
    return FAC_INST[f"{class_name}/{local_id}"]


def part_iri(canonical_id: str) -> URIRef:
    return FAC_INST[f"Part/{canonical_id}"]


@dataclass(frozen=True)
class FieldSpec:
    column: str
    predicate: URIRef
    kind: str  # "string" | "integer" | "ref" | "part_ref"
    ref_class: str | None = None  # for kind == "ref": target class name for entity_iri()


@dataclass(frozen=True)
class TableSpec:
    system: str
    table: str
    pk_column: str
    class_name: str
    fields: tuple[FieldSpec, ...]


TABLE_SPECS: dict[tuple[str, str], TableSpec] = {}


def _register(spec: TableSpec) -> None:
    TABLE_SPECS[(spec.system, spec.table)] = spec


_register(
    TableSpec(
        system="erp",
        table="suppliers",
        pk_column="supplier_id",
        class_name="Supplier",
        fields=(
            FieldSpec("supplier_id", FAC.supplierId, "string"),
            FieldSpec("name", RDFS.label, "string"),
            FieldSpec("status", FAC.status, "string"),
            FieldSpec("lead_time_days", FAC.leadTimeDays, "integer"),
            FieldSpec("risk_class", FAC.riskClass, "string"),
        ),
    )
)

_register(
    TableSpec(
        system="erp",
        table="parts",
        pk_column="part_id",
        class_name="__erp_part_row__",  # not used: parts rows resolve to fac:Part via identity, handled specially (see map_row).
        fields=(),
    )
)

_register(
    TableSpec(
        system="erp",
        table="purchase_orders",
        pk_column="po_id",
        class_name="PurchaseOrder",
        fields=(
            FieldSpec("po_id", FAC.poId, "string"),
            FieldSpec("status", FAC.status, "string"),
            FieldSpec("promised_at", FAC.promisedAt, "integer"),
            FieldSpec("expected_at", FAC.expectedAt, "integer"),
            FieldSpec("delay_reason", FAC.delayReason, "string"),
            FieldSpec("supplier_id", FAC.suppliedBy, "ref", ref_class="Supplier"),
        ),
    )
)

_register(
    TableSpec(
        system="erp",
        table="purchase_order_lines",
        pk_column="id",
        class_name="PurchaseOrderLine",
        fields=(
            FieldSpec("part_id", FAC.part, "part_ref"),
            FieldSpec("qty", FAC.quantity, "integer"),
            FieldSpec("destination_warehouse", FAC.destinationWarehouse, "ref", ref_class="Warehouse"),
            # Phase 4 gap fix (docs/experiment/implementation-notes.md Phase 4
            # section): the row's own po_id column was never mapped, so
            # Phase 4's work_order_risk projection had no way to find a
            # PurchaseOrder's lines via SPARQL. A plain forward "ref" (this
            # row's own subject -> its owning PurchaseOrder), same as every
            # other ref field here — NOT an inverse/backlink stored on the
            # PurchaseOrder's own subject: store.py's upsert-by-subject
            # retracts a subject's ENTIRE triple set whenever THAT subject's
            # own row is reprocessed, so a backlink written on the PARENT's
            # subject gets silently wiped the next time the parent's own row
            # event is applied (an inverse_ref kind was tried first and hit
            # exactly this — non-deterministically, depending on CDC
            # snapshot delivery order between the two tables; see
            # implementation-notes.md for the empirical finding).
            FieldSpec("po_id", FAC.purchaseOrder, "ref", ref_class="PurchaseOrder"),
        ),
    )
)

_register(
    TableSpec(
        system="mes",
        table="production_lines",
        pk_column="line_id",
        class_name="ProductionLine",
        fields=(
            FieldSpec("line_id", FAC.lineId, "string"),
            FieldSpec("status", FAC.status, "string"),
            FieldSpec("capabilities", FAC.capabilities, "json_string"),
        ),
    )
)

_register(
    TableSpec(
        system="mes",
        table="work_orders",
        pk_column="work_order_id",
        class_name="WorkOrder",
        fields=(
            FieldSpec("work_order_id", FAC.workOrderId, "string"),
            FieldSpec("status", FAC.status, "string"),
            FieldSpec("priority", FAC.priority, "string"),
            FieldSpec("planned_start", FAC.plannedStart, "integer"),
            FieldSpec("planned_finish", FAC.plannedFinish, "integer"),
            FieldSpec("warehouse", FAC.warehouse, "ref", ref_class="Warehouse"),
            FieldSpec("production_line_id", FAC.productionLine, "ref", ref_class="ProductionLine"),
        ),
    )
)

_register(
    TableSpec(
        system="mes",
        table="bom_requirements",
        pk_column="id",
        class_name="BomRequirement",
        fields=(
            FieldSpec("part_id", FAC.requiresPart, "part_ref"),
            FieldSpec("qty", FAC.quantity, "integer"),
            # Same Phase 4 gap fix as purchase_order_lines.po_id above: a
            # forward ref (this row -> its owning WorkOrder) so
            # work_order_risk can find a work order's requirements by SPARQL
            # instead of reading MES's database directly. See the comment on
            # purchase_order_lines.po_id above for why this is a forward
            # ref, not a backlink stored on the WorkOrder's own subject.
            FieldSpec("work_order_id", FAC.workOrder, "ref", ref_class="WorkOrder"),
        ),
    )
)

_register(
    TableSpec(
        system="wms",
        table="warehouses",
        pk_column="warehouse_id",
        class_name="Warehouse",
        fields=(
            FieldSpec("warehouse_id", FAC.warehouseId, "string"),
            FieldSpec("capacity_class", FAC.capacityClass, "string"),
            FieldSpec("region", FAC.region, "string"),
        ),
    )
)

_register(
    TableSpec(
        system="wms",
        table="inventory_lots",
        pk_column="lot_id",
        class_name="InventoryLot",
        fields=(
            FieldSpec("lot_id", FAC.lotId, "string"),
            FieldSpec("part", FAC.part, "part_ref"),
            FieldSpec("warehouse_id", FAC.warehouse, "ref", ref_class="Warehouse"),
            FieldSpec("on_hand", FAC.onHand, "integer"),
            FieldSpec("reserved", FAC.reserved, "integer"),
            FieldSpec("quality_status", FAC.qualityStatus, "string"),
        ),
    )
)


_register(
    TableSpec(
        system="wms",
        table="transfers",
        pk_column="action_execution_id",
        class_name="WmsTransferRecord",
        fields=(
            FieldSpec("action_execution_id", FAC.actionExecutionId, "string"),
            FieldSpec("source_warehouse", FAC.sourceWarehouse, "ref", ref_class="Warehouse"),
            FieldSpec("destination_warehouse", FAC.destinationWarehouse, "ref", ref_class="Warehouse"),
            FieldSpec("part", FAC.part, "part_ref"),
            FieldSpec("requested_quantity", FAC.requestedQuantity, "integer"),
            FieldSpec("actual_quantity", FAC.actualQuantity, "integer"),
            FieldSpec("status", FAC.transferStatus, "string"),
            FieldSpec("fault_mode_applied", FAC.faultModeApplied, "string"),
            FieldSpec("reverses_action_execution_id", FAC.reversesActionExecutionId, "string"),
        ),
    )
)


@dataclass
class MappedRow:
    entity_iri: URIRef
    class_name: str
    graph: rdflib.Graph
    identity_result: Resolved | Quarantined | None  # non-None iff a part_ref field was present


def resolve_entity_iri(
    system: str, table: str, pk_value: str, resolver: IdentityResolver
) -> URIRef | None:
    """The entity IRI for a (system, table, pk), independent of whether a
    full row is available. Needed for DELETE events, which carry a
    `before` image (or sometimes no row payload at all beyond the key) —
    store.py must still know which entity's observed triples to retract
    even though there is no `after` row to map (see consumer.py, and the
    bug this fixed: a delete previously left stale triples behind because
    entity identity was only ever derived from a full MappedRow)."""
    spec = TABLE_SPECS.get((system, table))
    if spec is None:
        return None
    if table == "parts" and system == "erp":
        result = resolver.resolve("ERP", str(pk_value))
        return part_iri(result.canonical_id) if isinstance(result, Resolved) else None
    return entity_iri(spec.class_name, str(pk_value))


def map_row(
    system: str, table: str, row: dict[str, Any] | None, resolver: IdentityResolver
) -> MappedRow | None:
    """row is Debezium's `after` image (None for a delete -> caller should
    use `before` for the pk/entity identity but map_row is only used to
    build the REPLACEMENT triples, so callers pass None on delete and skip
    calling this at all — see consumer.py)."""
    spec = TABLE_SPECS.get((system, table))
    if spec is None or row is None:
        return None

    if table == "parts" and system == "erp":
        return _map_erp_part(row, resolver)

    pk_value = row.get(spec.pk_column)
    if pk_value is None:
        return None
    subject = entity_iri(spec.class_name, str(pk_value))

    g = rdflib.Graph()
    g.add((subject, RDF.type, FAC[spec.class_name]))

    identity_result: Resolved | Quarantined | None = None

    for f in spec.fields:
        value = row.get(f.column)
        if value is None:
            continue
        if f.kind == "string":
            g.add((subject, f.predicate, Literal(str(value), datatype=XSD.string)))
        elif f.kind == "integer":
            g.add((subject, f.predicate, Literal(int(value), datatype=XSD.integer)))
        elif f.kind == "json_string":
            import json as _json

            g.add((subject, f.predicate, Literal(_json.dumps(value), datatype=XSD.string)))
        elif f.kind == "ref":
            g.add((subject, f.predicate, entity_iri(f.ref_class, str(value))))
        elif f.kind == "part_ref":
            # IdentityResolver / mapping_rules.yaml use the UPPERCASE system
            # keys from seed/out/identity_truth.json (ERP/MES/WMS); this
            # module's own `system` param is the lowercase
            # docker-compose/topic-routing convention (erp/mes/wms) — bug
            # caught empirically (a real canonical-fixture id resolved as
            # "unrecognized" until this .upper() was added).
            identity_result = resolver.resolve(system.upper(), str(value))
            if isinstance(identity_result, Resolved):
                g.add((subject, f.predicate, part_iri(identity_result.canonical_id)))
                g.add((part_iri(identity_result.canonical_id), RDF.type, FAC.Part))
            # Quarantined: the part_ref triple is simply omitted (never
            # guessed) — the rest of the row's fields still apply. The
            # QuarantinedIdentity provenance record is written separately
            # by services/ingestion/store.py from identity_result.
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown field kind {f.kind!r}")

    if table == "inventory_lots":
        on_hand = row.get("on_hand")
        reserved = row.get("reserved")
        if on_hand is not None and reserved is not None:
            g.add((subject, FAC.availableQuantity, Literal(int(on_hand) - int(reserved), datatype=XSD.integer)))

    return MappedRow(entity_iri=subject, class_name=spec.class_name, graph=g, identity_result=identity_result)


def _map_erp_part(row: dict[str, Any], resolver: IdentityResolver) -> MappedRow | None:
    """ERP's `parts` table is fac:Part's authoritative source
    (description/unit/criticality) but is keyed by ERP's OWN local id —
    the entity IRI must be the RESOLVED canonical part IRI, not
    fac-inst:Part/{erp_local_id}."""
    part_id = row.get("part_id")
    if part_id is None:
        return None
    identity_result = resolver.resolve("ERP", str(part_id))

    g = rdflib.Graph()
    if not isinstance(identity_result, Resolved):
        # Quarantined: no fac:Part triples can be written at all (we don't
        # even know which canonical part this row describes) — only the
        # QuarantinedIdentity provenance record (written by store.py).
        return MappedRow(entity_iri=URIRef(""), class_name="Part", graph=g, identity_result=identity_result)

    subject = part_iri(identity_result.canonical_id)
    g.add((subject, RDF.type, FAC.Part))
    g.add((subject, FAC.partId, Literal(identity_result.canonical_id, datatype=XSD.string)))
    if row.get("description") is not None:
        g.add((subject, FAC.description, Literal(str(row["description"]), datatype=XSD.string)))
    if row.get("unit") is not None:
        g.add((subject, FAC.unit, Literal(str(row["unit"]), datatype=XSD.string)))
    if row.get("criticality") is not None:
        g.add((subject, FAC.criticality, Literal(str(row["criticality"]), datatype=XSD.string)))

    return MappedRow(entity_iri=subject, class_name="Part", graph=g, identity_result=identity_result)
