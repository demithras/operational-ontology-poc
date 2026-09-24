# contracts/policies/v1/expedite_purchase_order.rego
#
# Contextual policy for the `expedite_purchase_order` ActionType
# (contracts/actions/v1/expedite_purchase_order.yaml) — candidate alternative
# B in docs/experiment/spec/03_domain_scenario.md's canonical incident.
# Simpler than transfer_inventory.rego (no safety-stock/quantity-threshold
# rule applies to expediting a PO — the operative business risk is cost, not
# inventory invariants) but follows the same shape/closure discipline: an
# expedite fee above `config.approval_threshold_cost` requires supervisor
# approval, and a purchase order that is already RECEIVED/CANCELLED (a
# terminal ERP status, docs/experiment/spec/03 "state-machine invariants")
# can never be expedited.
package factory.purchase_order.expedite

default decision := "deny"

valid_input if {
	is_number(input.parameters.expedite_fee)
	input.evidence.po_status != null
}

terminal_status if input.evidence.po_status in {"RECEIVED", "CANCELLED"}

hard_deny if not valid_input

hard_deny if terminal_status

needs_approval if {
	valid_input
	not terminal_status
	input.parameters.expedite_fee > input.config.approval_threshold_cost
}

decision := "deny" if hard_deny

decision := "require_approval" if {
	not hard_deny
	needs_approval
}

decision := "allow" if {
	not hard_deny
	not needs_approval
	valid_input
}

reasons contains "invalid_or_missing_required_input" if not valid_input

reasons contains "purchase_order_terminal" if terminal_status

reasons contains "approval_threshold_exceeded" if needs_approval

default obligations := []

obligations := [{"type": "approval", "relation": "can_approve_large_transfer"}] if needs_approval

result := {
	"decision": decision,
	"reasons": sort(reasons),
	"obligations": obligations,
}
