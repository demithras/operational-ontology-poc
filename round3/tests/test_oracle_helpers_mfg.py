"""One unit test per manufacturing helper, on a hand-built world (prose of spec/ops/manufacturing.json)."""
from r3_oracle import helpers as H
from tests.h23_util import view

CFG = {"safety_stock_units": {"default": 15, "overrides": [{"part": "P1", "warehouse": "WH-B", "units": 60}]}}


def world(**kw):
    objs = {"Part:P1": {}, "Part:P2": {}, "Warehouse:WH-A": {}, "Warehouse:WH-B": {}, "Warehouse:WH-C": {},
            "InventoryLot:LA1": {"onHand": 10, "reserved": 2}, "InventoryLot:LB1": {"onHand": 100, "reserved": 0},
            "InventoryLot:LC1": {"onHand": 5, "reserved": 5},
            "WorkOrder:W1": {"status": "PLANNED", "priority": "HIGH", "plannedStart": 20},
            "WorkOrder:W2": {"status": "DONE", "priority": "HIGH", "plannedStart": 20},
            "BomRequirement:B1": {"quantity": 50}, "BomRequirement:B2": {"quantity": 3},
            "PurchaseOrder:PO1": {"status": "OPEN", "expectedAt": 10}, "PurchaseOrder:PO2": {"status": "RECEIVED", "expectedAt": 5},
            "PurchaseOrder:PO3": {"status": "OPEN", "expectedAt": 99},
            "PurchaseOrderLine:L1": {"quantity": 7}, "PurchaseOrderLine:L2": {"quantity": 11},
            "PurchaseOrderLine:L3": {"quantity": 13}}
    objs.update(kw)
    links = [("PartReferencing_part", "InventoryLot:LA1", "Part:P1"), ("InventoryLot_warehouse", "InventoryLot:LA1", "Warehouse:WH-A"),
             ("PartReferencing_part", "InventoryLot:LB1", "Part:P1"), ("InventoryLot_warehouse", "InventoryLot:LB1", "Warehouse:WH-B"),
             ("PartReferencing_part", "InventoryLot:LC1", "Part:P1"), ("InventoryLot_warehouse", "InventoryLot:LC1", "Warehouse:WH-C"),
             ("WorkOrder_warehouse", "WorkOrder:W1", "Warehouse:WH-A"), ("WorkOrder_warehouse", "WorkOrder:W2", "Warehouse:WH-A"),
             ("BomRequirement_workOrder", "BomRequirement:B1", "WorkOrder:W1"), ("BomRequirement_requiresPart", "BomRequirement:B1", "Part:P1"),
             ("BomRequirement_workOrder", "BomRequirement:B2", "WorkOrder:W1"), ("BomRequirement_requiresPart", "BomRequirement:B2", "Part:P1"),
             ("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine:L1", "PurchaseOrder:PO1"),
             ("PartReferencing_part", "PurchaseOrderLine:L1", "Part:P1"), ("PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine:L1", "Warehouse:WH-A"),
             ("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine:L2", "PurchaseOrder:PO2"),
             ("PartReferencing_part", "PurchaseOrderLine:L2", "Part:P1"), ("PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine:L2", "Warehouse:WH-A"),
             ("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine:L3", "PurchaseOrder:PO3"),
             ("PartReferencing_part", "PurchaseOrderLine:L3", "Part:P1"), ("PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine:L3", "Warehouse:WH-A")]
    return view(objs, links, config=CFG)


def test_safety_stock_override_and_default():
    v = world()
    assert H.safety_stock(v, ("Part", "P1"), ("Warehouse", "WH-B")) == 60
    assert H.safety_stock(v, ("Part", "P1"), ("Warehouse", "WH-A")) == 15
    assert H.safety_stock(v, "P1", "WH-B") == 60


def test_available_quantity_missing_counts_zero():
    v = world(**{"InventoryLot:LX": {}})
    assert H.available_quantity(v, ("InventoryLot", "LA1")) == 8
    assert H.available_quantity(v, ("InventoryLot", "LX")) == 0


def test_incoming_before_filters_status_deadline_and_warehouse():
    v = world()
    # PO1 open expectedAt 10 (7 units); PO2 received (skipped); PO3 expectedAt 99 (after deadline)
    assert H.incoming_before(v, ("Part", "P1"), ("Warehouse", "WH-A"), 20) == 7
    assert H.incoming_before(v, ("Part", "P1"), ("Warehouse", "WH-A"), 100) == 20
    assert H.incoming_before(v, ("Part", "P1"), ("Warehouse", "WH-B"), 100) == 0


def test_work_order_risk_shortage_and_unknown_or_closed():
    v = world()  # need 53, have 8, incoming 7 -> short 38
    r = H.work_order_risk(v, ("WorkOrder", "W1"))
    assert (r["shortage"], r["at_risk"]) == (38, True)
    assert H.work_order_risk(v, ("WorkOrder", "W2"))["at_risk"] is False
    assert H.work_order_risk(v, ("WorkOrder", "NOPE"))["shortage"] == 0


def test_transfer_candidates_lists_other_warehouses_with_stock():
    v = world()
    c = H.transfer_candidates(v, ("WorkOrder", "W1"))
    assert [(x["candidate_id"], x["candidate_quantity"]) for x in c] == [("W1|P1|WH-B", 38)]  # WH-C has 0 available
    assert c[0]["destination_warehouse"] == "WH-A" and c[0]["source_warehouse"] == "WH-B"
    assert H.transfer_candidates(v, ("WorkOrder", "W2")) == []


def test_protecting_work_orders_route_match_priority_and_status():
    v = world()
    assert H.protecting_work_orders(v, ("Part", "P1"), ("Warehouse", "WH-B"), ("Warehouse", "WH-A")) == ["W1"]
    assert H.protecting_work_orders(v, ("Part", "P1"), ("Warehouse", "WH-C"), ("Warehouse", "WH-A")) == []
    low = world(**{"WorkOrder:W1": {"status": "PLANNED", "priority": "LOW", "plannedStart": 20}})
    assert H.protecting_work_orders(low, ("Part", "P1"), ("Warehouse", "WH-B"), ("Warehouse", "WH-A")) == []
