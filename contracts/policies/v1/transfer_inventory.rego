# contracts/policies/v1/transfer_inventory.rego
#
# Contextual business policy for the `transfer_inventory` ActionType
# (contracts/actions/v1/transfer_inventory.yaml). Implements
# docs/experiment/spec/03_domain_scenario.md's policy example exactly:
#
#   If transfer quantity <= 100
#   AND source inventory after transfer >= safety_stock
#   AND destination is compatible
#   THEN planner may approve.
#   Otherwise supervisor approval required.
#
# plus docs/experiment/spec/09_failure_and_adversarial_matrix.md F05/F06/F08
# and docs/experiment/spec/08_test_strategy.md "OPA tests" (below threshold
# allowed, above threshold requires approval, safety stock denial, quarantine
# denial, stale evidence denial/obligation, unknown required input =>
# non-allow — see transfer_inventory_test.rego for one test per item).
#
# "Destination is compatible" is simplified for this POC to "the destination
# warehouse resolves in the semantic core and is not under quarantine" —
# services/decision_service/evidence.py resolves warehouse existence via a
# closed-world closure check (INSUFFICIENT_EVIDENCE if it doesn't exist at
# all, before this policy ever runs) and passes quality_status here; a
# richer capacity/region compatibility model is out of scope for Phase 5.
# safety_stock and approval_threshold_units come from
# services/decision_service (the former read from data.json below, the
# latter from the ActionType contract's `policy.approval_threshold_units` —
# see contracts/actions/v1/transfer_inventory.yaml) — never invented here.
#
# Input contract (built by services/decision_service/policy.py):
#   {
#     "parameters": {"quantity": <int>, ...},
#     "evidence": {
#       "source_available": <int>,        # WMS current_inventory.available at proposal time
#       "safety_stock": <int>,            # data.safety_stock[part][warehouse], or default_safety_stock
#       "freshness_status": "FRESH"|"STALE",
#       "source_quality_status": "OK"|"QUARANTINE",
#       "destination_quality_status": "OK"|"QUARANTINE"
#     },
#     "config": {"approval_threshold_units": <int>}
#   }
#
# Output (spec 04's "structured policy result"): data.factory.inventory.transfer.result
#   {"decision": "allow"|"deny"|"require_approval", "reasons": [...], "obligations": [...]}
package factory.inventory.transfer

default decision := "deny"

remaining := input.evidence.source_available - input.parameters.quantity

# F02/F08/H14 closed-world closure: every field this policy reads must
# actually be present and correctly typed, or the input is treated as
# incomplete ("unknown required input => non-allow", 08_test_strategy.md).
# This is deliberately NOT the same INSUFFICIENT_EVIDENCE gate — that runs
# earlier in services/decision_service and never lets OPA see a request at
# all when required evidence is entirely absent; this is defense-in-depth
# for whatever DOES reach OPA (F24 "OPA evaluates ... input document" is the
# gate of record for anything OPA itself decides).
valid_input if {
	is_number(input.parameters.quantity)
	is_number(input.evidence.source_available)
	is_number(input.evidence.safety_stock)
	input.evidence.freshness_status != null
	input.evidence.source_quality_status != null
	input.evidence.destination_quality_status != null
}

hard_deny if not valid_input

hard_deny if input.evidence.freshness_status == "STALE"

hard_deny if input.evidence.source_quality_status == "QUARANTINE"

hard_deny if input.evidence.destination_quality_status == "QUARANTINE"

hard_deny if {
	valid_input
	remaining < input.evidence.safety_stock
}

needs_approval if {
	valid_input
	input.parameters.quantity > input.config.approval_threshold_units
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

reasons contains "stale_evidence" if input.evidence.freshness_status == "STALE"

reasons contains "source_quarantined" if input.evidence.source_quality_status == "QUARANTINE"

reasons contains "destination_quarantined" if input.evidence.destination_quality_status == "QUARANTINE"

reasons contains "safety_stock_breach" if {
	valid_input
	remaining < input.evidence.safety_stock
}

reasons contains "approval_threshold_exceeded" if needs_approval

# Stale evidence is a DENY (never a silent allow, F08), but still carries an
# explicit refresh obligation so a caller/UI knows exactly what unblocks it
# — "stale evidence deny/obligation" (08_test_strategy.md) is not an
# either/or in this implementation, it is both.
obligations := array.concat(approval_obligation, refresh_obligation)

# `default ... := []` (rather than a second "if not X" rule) so these stay
# defined even when `input.evidence` is entirely absent, not merely one
# field short — an "if not X" rule that itself reads a possibly-missing
# nested field would be undefined in exactly that case, which would make
# `obligations`, and therefore `result`, undefined too (caught empirically:
# transfer_inventory_test.rego's
# test_missing_evidence_block_entirely_is_non_allow failed with no
# `result` binding at all until this was switched to `default`).
default approval_obligation := []

approval_obligation := [{"type": "approval", "relation": "can_approve_large_transfer"}] if needs_approval

default refresh_obligation := []

refresh_obligation := [{"type": "refresh_evidence"}] if input.evidence.freshness_status == "STALE"

result := {
	"decision": decision,
	"reasons": sort(reasons),
	"obligations": obligations,
}
