"""Manufacturing: link types (owl:ObjectProperty) and observation types."""
from __future__ import annotations

from .common import DT, I, MANY, ONE, OPT1, S, enum, p
from .mfg_objects import ERP, FAC, MES, SHF, WMS
from .mfg_oo import OOC, OOO, SHA, SHD

RULE = "cardinality rule: SHACL min/maxCount wins; else the source SQL NOT NULL foreign key gives {1,1}; else {0,1}; to_cardinality {0,*} unless a source comment says otherwise"


def add_links(b):
    L = b.link
    L("PurchaseOrder_suppliedBy", "PurchaseOrder", "Supplier", ONE, MANY, src=f"{FAC} (fac:suppliedBy); {ERP} (purchase_orders.supplier_id NOT NULL)", note=RULE)
    L("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine", "PurchaseOrder", ONE, MANY, src=f"{FAC} (fac:purchaseOrder); {ERP} (purchase_order_lines.po_id NOT NULL)",
      note="the populated direction; the inverse fac:hasLine is documentation only and is not a link type here")
    L("PartReferencing_part", "PartReferencing", "Part", OPT1, MANY, src=f"{FAC} (fac:part range fac:Part); {SHF} (InventoryLotShape part maxCount 1)",
      note="from-end is the interface (shared property, no rdfs:domain); {0,1} is the weaker of InventoryLot (maxCount 1) and PurchaseOrderLine (SQL NOT NULL)")
    L("PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine", "Warehouse", ONE, MANY,
      src=f"{FAC} (fac:destinationWarehouse); {ERP} (purchase_order_lines.destination_warehouse NOT NULL)", note=RULE)
    L("InventoryLot_warehouse", "InventoryLot", "Warehouse", OPT1, MANY, src=f"{FAC} (fac:warehouse); {SHF} (InventoryLotShape warehouse maxCount 1)", note=RULE)
    L("WorkOrder_productionLine", "WorkOrder", "ProductionLine", ONE, MANY, src=f"{FAC} (fac:productionLine); {MES} (work_orders.production_line_id NOT NULL)", note=RULE)
    L("WorkOrder_warehouse", "WorkOrder", "Warehouse", ONE, MANY, src=f"{MES} (work_orders.warehouse NOT NULL); contracts/projections/v2/work_order_risk.yaml (?wo fac:warehouse)",
      note="used by projections and reference_model but NOT declared for WorkOrder in fac-core.ttl (fac:warehouse has domain InventoryLot): see decisions")
    L("BomRequirement_workOrder", "BomRequirement", "WorkOrder", ONE, MANY, src=f"{FAC} (fac:workOrder); {MES} (bom_requirements.work_order_id NOT NULL)", note="the populated direction; fac:hasRequirement not modelled")
    L("BomRequirement_requiresPart", "BomRequirement", "Part", ONE, MANY, src=f"{FAC} (fac:requiresPart); {MES} (bom_requirements.part_id NOT NULL)", note=RULE)
    L("WmsTransferRecord_sourceWarehouse", "WmsTransferRecord", "Warehouse", ONE, MANY, src=f"{FAC} (fac:sourceWarehouse); {WMS} (transfers.source_warehouse NOT NULL)", note=RULE)
    L("Decision_actor", "Decision", "ProvAgent", ONE, MANY, src=f"{OOC} (oo:actor range prov:Agent); {SHD} (minCount 1, maxCount 1)")
    L("Decision_evidenceSnapshot", "Decision", "EvidenceSnapshot", ONE, MANY, src=f"{OOC} (oo:evidenceSnapshot); {SHD} (minCount 1, maxCount 1)")
    for name, tgt in (("authorizationCheck", "AuthorizationCheck"), ("policyEvaluation", "PolicyEvaluation"),
                      ("conformanceCheck", "ConformanceCheck")):
        L(f"Decision_{name}", "Decision", tgt, OPT1, MANY, src=f"{OOC} (oo:{name})", note="at most one per decision (assumed from the single-valued property use; no shape)")
    L("Decision_approvedBy", "Decision", "ProvAgent", OPT1, MANY, src=f"{OOC} (oo:approvedBy range prov:Agent)")
    L("Decision_executedBy", "Decision", "ProvAgent", OPT1, MANY, src=f"{OOC} (oo:executedBy range prov:Agent)")
    L("Decision_actionExecution", "Decision", "ActionExecution", OPT1, ONE, src=f"{OOC} (oo:actionExecution: 'One per Decision')")
    for name, tgt in (("concernsWorkOrder", "WorkOrder"), ("concernsPart", "Part"), ("concernsSourceWarehouse", "Warehouse"),
                      ("concernsDestinationWarehouse", "Warehouse")):
        L(f"Decision_{name}", "Decision", tgt, OPT1, MANY, src=f"{OOC} (oo:{name}: domain oo:Decision, no range declared)",
          note=f"range not declared in the ontology; {tgt} chosen from the property name and reference_model Decision.params (see decisions)")
    L("ActionExecution_sourceWarehouse", "ActionExecution", "Warehouse", OPT1, MANY, src=f"{OOC} (oo:sourceWarehouse); {SHA} (minCount 0, maxCount 1)")
    L("ActionExecution_destinationWarehouse", "ActionExecution", "Warehouse", OPT1, MANY, src=f"{OOC} (oo:destinationWarehouse); {SHA} (minCount 0, maxCount 1)")
    L("ActionExecution_outcome", "ActionExecution", "Outcome", OPT1, ONE, src=f"{OOC} (oo:outcome: 'H1 observed outcome identifier')")
    L("SoftwareAgent_actsOnBehalfOf", "SoftwareAgent", "HumanActor", OPT1, MANY, src=f"{OOC} (oo:actsOnBehalfOf: populated only when oo:actor is a SoftwareAgent)")
    L("Observation_mappingRuleUsed", "Observation", "IdentityMapping", OPT1, MANY, src=f"{OOO} (oo:mappingRuleUsed: 'the IdentityMapping (if any) used')",
      note="range not declared; IdentityMapping per the property comment")
    L("IdentityMapping_canonicalId", "IdentityMapping", "Part", OPT1, MANY, src=f"{OOO} (oo:canonicalId, domain IdentityMapping); {FAC} (fac:Part: 'IRI = part:{{canonical_id}}')",
      note="range not declared; Part per the fac:Part comment (the only resolved canonical entity in the sources)")


def add_observations(b):
    O = b.observation
    obs = f"{OOO} (oo:Observed fact kind = truth_status observed; oo:Observation = the CDC event); "
    erp = obs + f"{FAC} ('authoritative_source: ERP' comments); contracts/actions/v3/expedite_purchase_order.yaml (observation.source ERP_CDC)"
    mes = obs + f"{FAC} ('authoritative_source: MES' comments); contracts/actions/v3/reschedule_work_order.yaml (observation.source MES_CDC)"
    wms = obs + f"{FAC} (fac:InventoryLot / fac:WmsTransferRecord); contracts/actions/v3/transfer_inventory.yaml (observation.source WMS_CDC)"
    O("SupplierObserved", "Supplier", [p("status"), p("leadTimeDays", I), p("riskClass")], "ERP_CDC", src=erp, note="ERP-authoritative properties only")
    O("PartObserved", "Part", [p("description"), p("unit"), p("criticality")], "ERP_CDC", src=erp, note="ERP-authoritative properties only")
    O("PurchaseOrderObserved", "PurchaseOrder", [p("status"), p("promisedAt", I), p("expectedAt", I), p("delayReason")], "ERP_CDC", src=erp)
    O("InventoryLotObserved", "InventoryLot", [p("onHand", I), p("reserved", I), p("qualityStatus")], "WMS_CDC", src=wms, note="InventoryLot.available is WMS-authoritative per fac-core.ttl header")
    O("WorkOrderObserved", "WorkOrder", [p("status"), p("priority"), p("plannedStart", I), p("plannedFinish", I)], "MES_CDC", src=mes, note="WorkOrder.status is MES-authoritative")
    O("ProductionLineObserved", "ProductionLine", [p("status"), p("capabilities")], "MES_CDC", src=mes)
    O("WmsTransferRecordObserved", "WmsTransferRecord", [p("transferStatus"), p("requestedQuantity", I), p("actualQuantity", I),
                                                         p("faultModeApplied"), p("reversesActionExecutionId")], "WMS_CDC", src=wms + "; contracts/reconciliation/v1/predicates.yaml (observation_source)",
      note="the correlated record reconciliation evaluates (CDC-correlated by action_execution_id)")
