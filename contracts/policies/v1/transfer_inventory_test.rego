# contracts/policies/v1/transfer_inventory_test.rego
#
# `opa test --fail-on-empty contracts/policies/v1` (Makefile `test-contracts`).
# One test per docs/experiment/spec/08_test_strategy.md "OPA tests" item.
package factory.inventory.transfer_test

import data.factory.inventory.transfer

base_evidence := {
	"source_available": 140,
	"safety_stock": 50,
	"freshness_status": "FRESH",
	"source_quality_status": "OK",
	"destination_quality_status": "OK",
}

base_config := {"approval_threshold_units": 100}

# Canonical incident: transfer 60 of 140 available, safety_stock 50,
# remaining 80 >= 50 -> allow. Matches seed/fixtures/canonical_incident.yaml.
test_below_threshold_allowed if {
	result := transfer.result with input as {
		"parameters": {"quantity": 60},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision == "allow"
	count(result.reasons) == 0
}

test_above_threshold_requires_approval if {
	result := transfer.result with input as {
		"parameters": {"quantity": 150},
		"evidence": object.union(base_evidence, {"source_available": 300}),
		"config": base_config,
	}
	result.decision == "require_approval"
	result.reasons == ["approval_threshold_exceeded"]
	result.obligations == [{"type": "approval", "relation": "can_approve_large_transfer"}]
}

test_safety_stock_denial if {
	# 140 available - 100 requested = 40 remaining, below safety_stock 50.
	result := transfer.result with input as {
		"parameters": {"quantity": 100},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["safety_stock_breach"]
}

test_source_quarantine_denial if {
	result := transfer.result with input as {
		"parameters": {"quantity": 10},
		"evidence": object.union(base_evidence, {"source_quality_status": "QUARANTINE"}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["source_quarantined"]
}

test_destination_quarantine_denial if {
	result := transfer.result with input as {
		"parameters": {"quantity": 10},
		"evidence": object.union(base_evidence, {"destination_quality_status": "QUARANTINE"}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["destination_quarantined"]
}

test_stale_evidence_denial_and_obligation if {
	result := transfer.result with input as {
		"parameters": {"quantity": 10},
		"evidence": object.union(base_evidence, {"freshness_status": "STALE"}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["stale_evidence"]
	result.obligations == [{"type": "refresh_evidence"}]
}

test_unknown_required_input_is_non_allow if {
	result := transfer.result with input as {
		"parameters": {},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision != "allow"
	result.reasons == ["invalid_or_missing_required_input"]
}

test_missing_evidence_block_entirely_is_non_allow if {
	result := transfer.result with input as {"parameters": {"quantity": 10}, "config": base_config}
	result.decision != "allow"
}

# Boundary: exactly at the threshold is still a planner-approvable allow
# ("quantity <= 100" per 03_domain_scenario.md, not "< 100").
test_exactly_at_threshold_is_allowed if {
	result := transfer.result with input as {
		"parameters": {"quantity": 100},
		"evidence": object.union(base_evidence, {"source_available": 300}),
		"config": base_config,
	}
	result.decision == "allow"
}

# Boundary: exactly at the safety-stock floor is still allowed
# ("source inventory after transfer >= safety_stock").
test_exactly_at_safety_stock_is_allowed if {
	result := transfer.result with input as {
		"parameters": {"quantity": 90},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision == "allow"
}
