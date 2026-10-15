"""Neutral authority fixtures (principals, agents, service accounts, grant rules, delegations) per domain."""

SEMANTICS = [
    "A request is allowed iff at least one allow grant matches (principal selector, resource selector, operation) and no deny grant matches. No matching allow means deny; deny overrides allow.",
    "A principal selector {relation, on_type} matches when the principal holds that relation on EVERY input resource of type on_type, and at least one such input exists.",
    "A resource selector {type: T} matches when some input resource conforms to T; {any: true} always matches.",
    "Operation patterns: exact name, '*', or '<prefix>:*'. Approval operations are named 'approval:<name>'.",
    "On-behalf-of: an agent acting for a delegator is allowed only if (a) the agent's own grants allow the operation, (b) the matching allow grant is delegable, and (c) the delegator would be allowed the same request. A deny matching the agent or any principal in its delegation chain denies.",
    "An approver must be a different principal than the requester and outside the requester's delegation chain.",
    "Direct canonical-state writes outside governed operations are denied for every principal (deny grant on 'write:canonical-state').",
    "Possessing a token or knowing an operation name is never authorization; only the grants above are.",
]
WRITERS = ["paladin-service", "conventional-service"]


def g(id_, effect, principal, resource, operation, delegable=False, origin="round2", note=None):
    d = {"id": id_, "effect": effect, "principal": principal, "resource": resource, "operation": operation,
         "delegable": delegable, "origin": origin}
    if note:
        d["note"] = note
    return d


def rel(rel_, type_="Warehouse"): return {"relation": rel_, "on_type": type_}


def human(pid, roles=(), relations=(), **kw): return {"id": pid, "kind": "human", "roles": list(roles), "relations": list(relations), "delegated_by": None, **kw}


def agent(pid, roles, relations, delegated_by, hostile=False, note=""):
    return {"id": pid, "kind": "agent", "roles": list(roles), "relations": list(relations), "delegated_by": delegated_by,
            "hostile": hostile, "note": note}


def _whs(relation, whs=("WH-A", "WH-B", "WH-C")):
    return [{"type": "Warehouse", "key": w, "relation": relation} for w in whs]


def manufacturing():
    admin_rel = _whs("planner") + _whs("supervisor") + _whs("senior_approver")
    principals = [
        human("planner-1", ["planner"], _whs("planner")), human("junior-1", ["junior_planner"], _whs("junior_planner")),
        human("supervisor-1", ["supervisor"], _whs("supervisor")), human("senior-1", ["senior_approver"], _whs("senior_approver")),
        human("nobody-1", ["none"], []), human("admin-1", ["admin"], admin_rel),
        agent("agent-1", ["agent"], _whs("agent_grant"), "planner-1", note="delegated planner agent: transfer_inventory on all warehouses"),
        agent("agent-hostile-1", ["agent"], _whs("agent_grant", ("WH-B", "WH-C")), "planner-1", True,
              "compromised agent with a legitimately narrower grant: transfers only between WH-B and WH-C"),
        agent("agent-orphan", ["agent"], _whs("agent_grant"), "nobody-1", note="delegator holds nothing: effectively no authority"),
    ]
    grants = [
        g("transfer-inventory-planner", "allow", rel("planner"), {"type": "Warehouse"}, "transfer_inventory"),
        g("transfer-inventory-junior-planner", "allow", rel("junior_planner"), {"type": "Warehouse"}, "transfer_inventory"),
        g("transfer-inventory-agent-grant", "allow", rel("agent_grant"), {"type": "Warehouse"}, "transfer_inventory", True),
        g("approve-large-transfer-senior-approver", "allow", rel("senior_approver"), {"type": "Warehouse"}, "approval:large_transfer"),
        g("approve-large-transfer-supervisor", "allow", rel("supervisor"), {"type": "Warehouse"}, "approval:large_transfer_v1",
          note="Round 2 rule; no operation requests this approval name (kept for faithful derivation)"),
        g("mitigate-high-priority-planner", "allow", rel("planner"), {"type": "Warehouse"}, "mitigate_high_priority",
          note="realised as the protected-route business rule of transfer_inventory, not as a separate operation"),
        g("mitigate-high-priority-supervisor", "allow", rel("supervisor"), {"type": "Warehouse"}, "mitigate_high_priority"),
        g("neutral-planner-expedite", "allow", {"role": "planner"}, {"any": True}, "expedite_purchase_order", origin="neutral-fix",
          note="Round 2 IR names rules for the wrong capability so expedite is unauthorizable there (FINDING in round2 tests); the neutral workload grants planners"),
        g("neutral-planner-reschedule", "allow", {"role": "planner"}, {"any": True}, "reschedule_work_order", origin="neutral-fix"),
        g("neutral-supervisor-approve-expedite", "allow", {"role": "supervisor"}, {"any": True}, "approval:expedite", origin="neutral-fix"),
        g("neutral-supervisor-approve-reschedule", "allow", {"role": "supervisor"}, {"any": True}, "approval:reschedule", origin="neutral-fix"),
        g("neutral-admin-all", "allow", {"role": "admin"}, {"any": True}, "*", origin="neutral-extension", note="the upper bound agents are compared against"),
        g("no-canonical-write-outside-operations", "deny", {"any": True}, {"any": True}, "write:canonical-state", origin="neutral-extension"),
    ]
    return {"principals": principals, "grants": grants,
            "delegations": [{"agent": "agent-1", "on_behalf_of": "planner-1", "operations": ["transfer_inventory"]},
                            {"agent": "agent-hostile-1", "on_behalf_of": "planner-1", "operations": ["transfer_inventory"]},
                            {"agent": "agent-orphan", "on_behalf_of": "nobody-1", "operations": ["transfer_inventory"]}],
            "service_accounts": _services(["WMS", "ERP", "MES"])}


def _services(adapters):
    out = [{"id": "svc-core", "kind": "service", "purpose": "the deployed variant's own service identity",
            "world_writers": list(WRITERS), "operation_grants": []}]
    out += [{"id": f"svc-{a.lower()}", "kind": "service", "purpose": f"external system adapter {a}",
             "world_writers": [a], "operation_grants": []} for a in adapters]
    return out


def project():
    res = {"role": "researcher"}
    ops = ["create_hypothesis", "edit_threshold", "preregister_hypothesis", "new_experiment_version", "start_run",
           "attach_evidence", "evaluate_hypothesis", "supersede_hypothesis", "record_decision", "flag_orphan_component"]
    principals = [
        human("researcher-1", ["researcher"]), human("researcher-2", ["researcher"]), human("viewer-1", []),
        human("admin-1", ["admin"]),
        agent("agent-evidence-1", ["evidence-agent"], [], None, True, "compromised evidence-collection agent: may only start runs and attach evidence"),
        agent("agent-draft-1", ["draft-agent"], [], None, False, "drafting agent: may only create hypotheses and record decisions"),
    ]
    grants = [g(f"researcher-{o.replace('_', '-')}", "allow", res, {"any": True}, o) for o in ops]
    grants += [g("neutral-admin-all", "allow", {"role": "admin"}, {"any": True}, "*", origin="neutral-extension"),
               g("neutral-evidence-agent-run", "allow", {"role": "evidence-agent"}, {"any": True}, "start_run", origin="neutral-extension"),
               g("neutral-evidence-agent-attach", "allow", {"role": "evidence-agent"}, {"any": True}, "attach_evidence", origin="neutral-extension"),
               g("neutral-draft-agent-create", "allow", {"role": "draft-agent"}, {"any": True}, "create_hypothesis", origin="neutral-extension"),
               g("neutral-draft-agent-decision", "allow", {"role": "draft-agent"}, {"any": True}, "record_decision", origin="neutral-extension"),
               g("no-direct-verdict-write", "deny", {"any": True}, {"any": True}, "write:Verdict.value"),
               g("no-threshold-edit-after-preregistration", "deny", {"any": True}, {"type": "Threshold", "state": "governed hypothesis not DRAFT"}, "update:Threshold"),
               g("no-canonical-write-outside-operations", "deny", {"any": True}, {"any": True}, "write:canonical-state")]
    return {"principals": principals, "grants": grants, "delegations": [],
            "service_accounts": _services([]),
            "delegation_note": "Every Round 2 project grant is delegation_allowed=false: on_behalf_of is never valid in this domain."}
