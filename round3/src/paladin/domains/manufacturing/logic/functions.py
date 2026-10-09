"""Manufacturing Function implementations, keyed by Function.implementation_ref: impl(view, args) -> value."""
from __future__ import annotations

import json

from paladin.domains._support import canonical_json, sha256_hex
from . import facts


def available_quantity(view, args):  # reference_model.state:InventoryLot.available
    rec = view.get("InventoryLot", args["lot"])
    p = rec["props"]
    return p.get("onHand", 0) - p.get("reserved", 0)


def incoming_before(view, args):  # reference_model.derive:_incoming_before
    return facts.incoming_before(view, args["part"], args["warehouse"], args["deadline"])


def work_order_risk(view, args):  # reference_model.derive:work_order_risk (shortage, at_risk)
    r = facts.risk(view, args["work_order"])
    return {"work_order_id": r["work_order_id"], "shortage": r["shortage"], "at_risk": r["at_risk"]}


def recommend_transfer(view, args):  # decision-service recommender (largest candidate, ties by candidate_id)
    wo_id = args["work_order"]
    r = facts.risk(view, wo_id)
    cands = facts.candidates(view, wo_id)
    if not r["at_risk"] or not cands:
        return None
    best = sorted(cands, key=lambda c: (-c["candidate_quantity"], c["candidate_id"]))[0]
    return {"action_type": "transfer_inventory",
            "parameters": {"source_warehouse": best["source_warehouse"],
                           "destination_warehouse": best["destination_warehouse"], "part": best["part"],
                           "quantity": min(best["candidate_quantity"], r["shortage"]), "work_order": wo_id},
            "context": {}}


def decision_content_hash(view, args):  # services.decision_service.hashing.decision_content_hash
    d = view.get("Decision", args["decision"])
    if d is None:
        raise ValueError("decision does not exist")  # a deliberate helper error, not an unguarded subscript
    p = d["props"]
    actor = view.follow("Decision_actor", "Decision", d["key"])
    snap = view.follow("Decision_evidenceSnapshot", "Decision", d["key"])
    if not actor or not snap:
        raise ValueError("decision has no actor or no evidence snapshot link")
    a = actor[0]
    behalf = view.follow("SoftwareAgent_actsOnBehalfOf", "SoftwareAgent", a["key"]) if a["type"] == "SoftwareAgent" else ()
    payload = {
        "actor_type": "agent" if a["type"] == "SoftwareAgent" else "human",
        "actor_id": a["key"],
        "principal_actor_id": behalf[0]["key"] if behalf else None,
        "evidence_snapshot_id": snap[0]["key"],
        "ontology_version": p.get("ontologyVersion"), "shape_set_version": p.get("shapeSetVersion"),
        "authorization_model_version": p.get("authorizationModelVersion"),
        "policy_bundle_version": p.get("policyBundleVersion"), "action_type": p.get("actionType"),
        "action_version": p.get("actionVersion"), "parameters": json.loads(p.get("parametersJson") or "{}"),
    }
    return sha256_hex(canonical_json(payload))


def resolve_canonical_id(view, args):  # reference_model.transitions.resolve_id: pass through when unmapped
    sid = args["source_local_id"]
    for m in view.list("IdentityMapping"):
        if m["props"].get("sourceLocalId") == sid:
            hits = view.follow("IdentityMapping_canonicalId", "IdentityMapping", m["key"])
            if hits:
                return hits[0]["key"]
    return sid


# keyed by the function name after ':' in the IR implementation_ref (the module path in front is a Round 2 import
# location that carries no behaviour); __init__.build_bindings expands each name to the full refs the IR declares
BY_NAME = {
    "InventoryLot.available": available_quantity,
    "_incoming_before": incoming_before,
    "work_order_risk": work_order_risk,
    "recommend_transfer_for_work_order": recommend_transfer,
    "decision_content_hash": decision_content_hash,
    "resolve_id": resolve_canonical_id,
}
