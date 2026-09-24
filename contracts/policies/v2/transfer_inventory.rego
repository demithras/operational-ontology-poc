# contracts/policies/v2/transfer_inventory.rego
#
# Phase 7 (docs/experiment/spec/07_versioning_and_replay.md) V2 policy for
# transfer_inventory — see contracts/actions/v2/transfer_inventory.yaml's
# header for the full list of what changed. Package is
# `factory.inventory.transfer_v2`, DISTINCT from v1's
# `factory.inventory.transfer` — both are loaded into the SAME live OPA
# instance simultaneously (docker-compose.yml mounts the whole
# contracts/policies/ tree), so a V1 decision's historical replay can
# always re-evaluate against `factory.inventory.transfer` exactly as it did
# at proposal time, while every NEW V2+ proposal uses this package instead.
#
# Input contract (built by services/decision_service/policy.py's V2 branch):
#   {
#     "parameters": {"quantity": <int>},
#     "evidence": {
#       "on_hand": <int>, "reserved": <int>,       # NEW: replace v1's source_available
#       "reservation_ok": <bool>,                  # NEW required evidence field
#       "safety_stock": <int>,                     # from data.json's safety_stock_v2 (changed policy)
#       "freshness_status": "FRESH"|"STALE",
#       "source_quality_status": "OK"|"QUARANTINE",
#       "destination_quality_status": "OK"|"QUARANTINE"
#     },
#     "config": {"approval_threshold_units": <int>}
#   }
package factory.inventory.transfer_v2

default decision := "deny"

remaining := input.evidence.on_hand - input.evidence.reserved - input.parameters.quantity

valid_input if {
	is_number(input.parameters.quantity)
	is_number(input.evidence.on_hand)
	is_number(input.evidence.reserved)
	is_number(input.evidence.safety_stock)
	input.evidence.reservation_ok != null
	input.evidence.freshness_status != null
	input.evidence.source_quality_status != null
	input.evidence.destination_quality_status != null
}

hard_deny if not valid_input

hard_deny if input.evidence.freshness_status == "STALE"

hard_deny if input.evidence.source_quality_status == "QUARANTINE"

hard_deny if input.evidence.destination_quality_status == "QUARANTINE"

# V2's changed safety-stock policy, part 1: the reservation itself must be
# data-consistent (reserved <= on_hand) — new in V2, no v1 equivalent.
hard_deny if {
	valid_input
	not input.evidence.reservation_ok
}

# V2's changed safety-stock policy, part 2: same remaining-inventory shape
# as v1, but computed from on_hand/reserved directly (never a retired
# `available` field) and checked against data.json's safety_stock_v2 value
# (services/decision_service/evidence.py resolves it) — for parts with no
# v2-specific override this is numerically higher than v1's default,
# a genuine, deliberate behavior divergence (see approval_threshold_units'
# comment in contracts/actions/v2/transfer_inventory.yaml).
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

reasons contains "reservation_inconsistent" if {
	valid_input
	not input.evidence.reservation_ok
}

reasons contains "safety_stock_breach" if {
	valid_input
	remaining < input.evidence.safety_stock
}

reasons contains "approval_threshold_exceeded" if needs_approval

obligations := array.concat(approval_obligation, refresh_obligation)

default approval_obligation := []

approval_obligation := [{"type": "approval", "relation": "can_approve_large_transfer"}] if needs_approval

default refresh_obligation := []

refresh_obligation := [{"type": "refresh_evidence"}] if input.evidence.freshness_status == "STALE"

result := {
	"decision": decision,
	"reasons": sort(reasons),
	"obligations": obligations,
}
