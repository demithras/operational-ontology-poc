"""Assemble the manufacturing IR + provenance (the CURRENT manufacturing product of this repo)."""
from __future__ import annotations

from .common import Builder
from .mfg_actions import add_actions, add_constraints
from .mfg_links import add_links, add_observations
from .mfg_logic import add_authority, add_functions, add_policies
from .mfg_objects import add_fac_interfaces, add_fac_objects
from .mfg_oo import add_observation_objects, add_oo_interfaces, add_oo_objects

DECISIONS = [
    "Package version `v3` = the deployed ontology, shapes and actions contract version (contracts/manifests/deployed_version.json: ontology v3, shapes v3, actions v3, policies v2, authorization v2, projections v2). Action versions are the integer `version` of each contract file rendered as `vN` (transfer_inventory 3, the other two 1); policy versions follow the directory they live in (policies/v2 only contains transfer_inventory; the other two Rego packages exist only in policies/v1, so they carry `v1`).",
    "ObjectProperty -> LinkType, DatatypeProperty -> property. IR link cardinality convention (read off the frozen examples, HypothesisHasEvidence {0,*}/{1,1}): from_cardinality is how many links a FROM-instance has, to_cardinality how many a TO-instance has. Values come from the rule quoted in each link's note; cardinalities the sources do not decide are {0,1} / {0,*}, which is a choice, not a fact.",
    "Every RDF class with no declared identifier property (PurchaseOrderLine, BomRequirement, Shipment, EvidenceSnapshot, DecisionActivity, AuthorizationCheck, PolicyEvaluation, ConformanceCheck, Observation, SourcePosition, IdentityResolutionActivity, IdentityMapping, QuarantinedIdentity) gets a synthetic primary key property `iri` (immutable, required). The IR demands a primary_key; the sources identify these by IRI only. Classes with a declared id (supplierId, partId, poId, lotId, warehouseId, workOrderId, lineId, decisionId, actionExecutionId, outcomeId) use it.",
    "`required` is true only for the primary key and for properties with sh:minCount >= 1 in contracts/shapes/v3 (Decision, Outcome, EvidenceSnapshot). The factory shapes declare no minCount, so factory properties are required=false although the source databases declare most columns NOT NULL (SQL nullability was used for foreign-key cardinality only). `immutable` is true for primary keys and for the hash-covered Decision fields (PINNED_DECISION_FIELDS); nothing else in the sources states immutability.",
    "Value vocabularies that the sources state only in comments, SQL CHECKs or SHACL sh:in are recorded as opaque property constraint strings `enum:A|B|C`; the IR has no enum type. `min_inclusive:N` records SHACL sh:minInclusive. These are atoms, not IR structure.",
    "WorkOrder.warehouse: contracts/projections/v2/work_order_risk.yaml, reference_model (WorkOrder.warehouse) and services/mes/schema.sql (work_orders.warehouse NOT NULL) use it, but fac-core.ttl declares fac:warehouse with domain InventoryLot only. Modelled as link WorkOrder_warehouse; the ontology file is insufficient on its own.",
    "oo:actorId / oo:actorRole declare no rdfs:domain; they are attached to both HumanActor and SoftwareAgent. oo:concernsWorkOrder/Part/SourceWarehouse/DestinationWarehouse, oo:mappingRuleUsed and oo:canonicalId declare no rdfs:range; targets WorkOrder, Part, Warehouse, Warehouse, IdentityMapping and Part were chosen from names, comments and reference_model Decision.params.",
    "Rego packages emit one of deny / require_approval / allow, but the IR Policy has a single decision: each Rego decision rule became its own Policy (`<action>_hard_deny`, `_needs_approval`, `_allow`; expression_ref `rego:<package>#<rule>`). No `classify` policy exists in the sources. Rego `reasons`/`obligations` are not representable and are not modelled.",
    "OpenFGA relations are mapped one rule per (relation alternative): `can_transfer_inventory = planner or junior_planner or agent_grant` became three allow rules; principal_selector `warehouse#planner` is the FGA userset notation. FGA has no deny and no per-rule delegation flag: all effects are allow; delegation_allowed is true only on the agent_grant rule (agents act on behalf of a user principal), false elsewhere. That flag is a choice, not a fact in model.fga.",
    "compensation: transfer_inventory is `compensatable` via the WMS operation reverse_transfer, which is NOT a governed Action in contracts/actions/*, and the IR compensation_action must name an Action. It is therefore null here and the information that a WMS reversal exists is not representable in the IR. reschedule_work_order compensates with itself (operation reschedule_work_order). expedite_purchase_order is manual_recovery_required (null).",
    "Action `context` (transfer_inventory context.work_order_id, required_for_evidence), `reads`, `evidence_requirements`, `closure`, `audit` and the expected_effects are not IR fields. closure/evidence content only appears indirectly (freshness constraint, outcome_predicate text). The three actions' `preconditions` keep the contract's own strings (they use the aliases `source`/`destination`/`source_available`).",
    "contracts/reconciliation/v1/predicates.yaml has an indentation anomaly (reschedule_work_order nested under expedite_purchase_order); the Action outcome_predicate texts were taken from each action contract's observation + expected_effects (and the exact_success rule for transfer_inventory), not from that nesting.",
    "fac:hasLine and fac:hasRequirement are 'documentation only, NOT populated' inverse declarations; they are not modelled as link types (a LinkType is navigable from both ends via its cardinalities). The retired fac:availableQuantity is not modelled; the Function available_quantity replaces it. oo:status on non-Decision resources (FactKindScheme concepts oo:Observed/Inferred/Derived/Asserted) is not modelled: the sources attach it to graph-level describing resources, not to a class.",
    "Observation types: one per authoritative source feed (ERP_CDC, MES_CDC, WMS_CDC, strings from the action contracts' observation.source), carrying only the properties that source owns per the fac:* 'authoritative_source' comments. truth_status `observed` is oo:Observed of contracts/ontology/v3/oo-observation.ttl (FactKindScheme). oo:Observation itself (the CDC event with LSN/version/op) and oo:SourcePosition / oo:IdentityMapping / oo:QuarantinedIdentity are ordinary object types, not ObservationTypes.",
    "Functions: only read/compute logic that exists in code is modelled (available_quantity, incoming_before, work_order_risk, recommend_transfer_for_work_order, decision_content_hash, resolve_canonical_id). invariants.py's expected_* oracle functions are test oracles, not product logic, and are not modelled. `reads` lists the ontology properties/links a function consults; for recommend_transfer_for_work_order the real read path is the hot projections, listed here as the object types they derive from.",
    "Constraints: hard = a violation is rejected outright (SHACL, SQL CHECK, invariants.py, Rego hard_deny, freshness); soft = a violation is allowed but routes to require_approval (the three approval thresholds). `scope` is an opaque atom (object type or action id).",
]


def build():
    b = Builder("manufacturing-ontology", "manufacturing", "v3", {"derived_from": "contracts/ontology/v3, contracts/shapes/v3, contracts/actions/v3, contracts/policies/v2, contracts/authorization/v2, reference_model, services/decision_service"})
    add_fac_interfaces(b)
    add_oo_interfaces(b)
    add_fac_objects(b)
    add_oo_objects(b)
    add_observation_objects(b)
    add_links(b)
    add_functions(b)
    add_authority(b)
    add_policies(b)
    add_actions(b)
    add_observations(b)
    add_constraints(b)
    for d in DECISIONS:
        b.decide(d)
    return b
