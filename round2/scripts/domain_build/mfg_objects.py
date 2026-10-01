"""Manufacturing: factory (fac:) object types, from contracts/ontology/v3/fac-core.ttl + shapes + source SQL."""
from __future__ import annotations

from .common import DT, I, S, enum, p

FAC = "contracts/ontology/v3/fac-core.ttl"
SHF = "contracts/shapes/v3/fac-core-shape.ttl"
ERP = "services/erp/schema.sql"
MES = "services/mes/schema.sql"
WMS = "services/wms/schema.sql"
IRI = "`iri`: RDF identity (no declared id property in the sources)"


def iri():
    return p("iri", S, True, True, d="RDF IRI of the instance; added because the IR requires a primary_key and the source class declares no id property")


def add_fac_objects(b):
    b.obj("Supplier", "supplierId", [
        p("supplierId", S, True, True), p("status", S, False, False, [enum("ACTIVE", "SUSPENDED")]),
        p("leadTimeDays", I), p("riskClass", S, False, False, [enum("LOW", "MEDIUM", "HIGH")])],
        ["Statused"], src=f"{FAC} (fac:Supplier, supplierId, status, leadTimeDays, riskClass)", note="status literals from the fac:status comment")
    b.obj("Part", "partId", [
        p("partId", S, True, True, d="Canonical part id, e.g. PX-0017"), p("description"), p("unit"),
        p("criticality", S, False, False, [enum("LOW", "MEDIUM", "HIGH", "CRITICAL")])],
        src=f"{FAC} (fac:Part, partId, description, unit, criticality); {SHF} (PartShape: partId maxCount 1)")
    b.obj("PurchaseOrder", "poId", [
        p("poId", S, True, True), p("status", S, False, False, [enum("OPEN", "DELAYED", "RECEIVED", "CANCELLED")]),
        p("promisedAt", I), p("expectedAt", I), p("delayReason")],
        ["Statused"], src=f"{FAC} (fac:PurchaseOrder, poId, status, promisedAt, expectedAt, delayReason)")
    b.obj("PurchaseOrderLine", "iri", [iri(), p("quantity", I)], ["PartReferencing", "Quantified"],
          src=f"{FAC} (fac:PurchaseOrderLine; fac:quantity and fac:part are shared properties)", note=IRI)
    b.obj("InventoryLot", "lotId", [
        p("lotId", S, True, True), p("onHand", I, False, False, ["min_inclusive:0"]),
        p("reserved", I, False, False, ["min_inclusive:0"]), p("qualityStatus", S, False, False, [enum("OK", "QUARANTINE")])],
        ["PartReferencing"], src=f"{FAC} (fac:InventoryLot); {SHF} (InventoryLotShape: onHand/reserved >= 0)",
        note="fac:availableQuantity is retired in v2+ (not modelled); available is the Function available_quantity")
    b.obj("Warehouse", "warehouseId", [
        p("warehouseId", S, True, True), p("capacityClass", S, False, False, [enum("SMALL", "MEDIUM", "LARGE")]), p("region")],
        src=f"{FAC} (fac:Warehouse, warehouseId, capacityClass, region)")
    b.obj("WorkOrder", "workOrderId", [
        p("workOrderId", S, True, True),
        p("status", S, False, False, [enum("PLANNED", "RELEASED", "RUNNING", "DONE", "CANCELLED")]),
        p("priority", S, False, False, [enum("LOW", "MEDIUM", "HIGH")]), p("plannedStart", I), p("plannedFinish", I)],
        ["Statused"], src=f"{FAC} (fac:WorkOrder); {MES} (work_orders)")
    b.obj("BomRequirement", "iri", [iri(), p("quantity", I)], ["Quantified"], src=f"{FAC} (fac:BomRequirement; fac:quantity shared)", note=IRI)
    b.obj("ProductionLine", "lineId", [
        p("lineId", S, True, True), p("status", S, False, False, [enum("ACTIVE", "MAINTENANCE")]),
        p("capabilities", S, d="MES JSONB capabilities array stored as its JSON-encoded string form in v1")],
        ["Statused"], src=f"{FAC} (fac:ProductionLine, lineId, status, capabilities)")
    b.obj("Shipment", "iri", [iri()], src=f"{FAC} (fac:Shipment)",
          note="declared class with no properties and no populated source; kept as declared (" + IRI + ")")
    b.obj("WmsTransferRecord", "actionExecutionId", [
        p("actionExecutionId", S, True, True), p("requestedQuantity", I), p("actualQuantity", I),
        p("transferStatus", S, False, False, [enum("COMMITTED", "PARTIAL", "FAILED", "REVERSED")]),
        p("faultModeApplied", S, d="test-mode only (OO_TEST_MODE=1)"), p("reversesActionExecutionId")],
        src=f"{FAC} (fac:WmsTransferRecord); {WMS} (transfers)",
        note="pk = the WMS idempotency key (unique per transfer row)")


def add_fac_interfaces(b):
    b.iface("Statused", [p("status", S)], src=f"{FAC} (fac:status: 'Shared status property; allowed literal set is per-domain')",
            note="shared datatype property declared once without rdfs:domain; implemented by Supplier, PurchaseOrder, WorkOrder, ProductionLine")
    b.iface("PartReferencing", [], ["PartReferencing_part"], src=f"{FAC} (fac:part: 'Shared reference-to-Part property (PurchaseOrderLine, InventoryLot)')",
            note="shared object property; the link type PartReferencing_part has this interface as its from-end")
    b.iface("Quantified", [p("quantity", I)], src=f"{FAC} (fac:quantity: 'Shared line/requirement quantity (PurchaseOrderLine, BomRequirement)')",
            note="shared datatype property")
