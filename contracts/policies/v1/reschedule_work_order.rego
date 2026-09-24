# contracts/policies/v1/reschedule_work_order.rego
#
# Contextual policy for the `reschedule_work_order` ActionType
# (contracts/actions/v1/reschedule_work_order.yaml) — candidate alternative C
# in docs/experiment/spec/03_domain_scenario.md's canonical incident.
# docs/experiment/spec/03 "state-machine invariants": "DONE/CANCELLED ->
# reschedule forbidden" is the hard invariant (matches MES's own 409 on those
# statuses, services/mes/app.py); rescheduling a HIGH-priority work order is
# the policy-level "protected" action junior_planner may not approve
# (03_domain_scenario.md "junior_planner: ... cannot approve
# high-priority-work-order mitigation" — reschedule is one such mitigation).
package factory.work_order.reschedule

default decision := "deny"

valid_input if {
	input.evidence.work_order_status != null
	input.evidence.priority != null
}

terminal_status if input.evidence.work_order_status in {"DONE", "CANCELLED"}

hard_deny if not valid_input

hard_deny if terminal_status

needs_approval if {
	valid_input
	not terminal_status
	input.evidence.priority == "HIGH"
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

reasons contains "work_order_terminal" if terminal_status

reasons contains "high_priority_requires_approval" if needs_approval

default obligations := []

obligations := [{"type": "approval", "relation": "can_approve_large_transfer"}] if needs_approval

result := {
	"decision": decision,
	"reasons": sort(reasons),
	"obligations": obligations,
}
