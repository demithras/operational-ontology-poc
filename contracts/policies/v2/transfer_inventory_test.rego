# contracts/policies/v2/transfer_inventory_test.rego
#
# `opa test --fail-on-empty contracts/policies` (Makefile `test-contracts`).
# Same coverage shape as contracts/policies/v1/transfer_inventory_test.rego,
# adapted for V2's on_hand/reserved/reservation_ok evidence shape.
package factory.inventory.transfer_v2_test

import data.factory.inventory.transfer_v2

base_evidence := {
	"on_hand": 140,
	"reserved": 0,
	"reservation_ok": true,
	"safety_stock": 50,
	"freshness_status": "FRESH",
	"source_quality_status": "OK",
	"destination_quality_status": "OK",
}

base_config := {"approval_threshold_units": 80}

test_below_threshold_allowed if {
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 60},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision == "allow"
	count(result.reasons) == 0
}

test_above_threshold_requires_approval if {
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 90},
		"evidence": object.union(base_evidence, {"on_hand": 300}),
		"config": base_config,
	}
	result.decision == "require_approval"
	result.reasons == ["approval_threshold_exceeded"]
}

test_safety_stock_denial if {
	# 90 on_hand - 0 reserved - 45 requested = 45 remaining, below 50 --
	# quantity stays <= the 80-unit approval threshold so this isolates the
	# safety-stock reason alone.
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 45},
		"evidence": object.union(base_evidence, {"on_hand": 90}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["safety_stock_breach"]
}

test_reservation_inconsistent_denial if {
	# New in V2: reserved > on_hand is a hard_deny. remaining = on_hand -
	# reserved - quantity necessarily also goes deeply negative whenever
	# reserved > on_hand, so safety_stock_breach fires alongside it -- both
	# reasons are correct here, not a second independent scenario.
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 1},
		"evidence": object.union(base_evidence, {"reservation_ok": false, "reserved": 200}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["reservation_inconsistent", "safety_stock_breach"]
}

test_source_quarantine_denial if {
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 10},
		"evidence": object.union(base_evidence, {"source_quality_status": "QUARANTINE"}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["source_quarantined"]
}

test_stale_evidence_denial_and_obligation if {
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 10},
		"evidence": object.union(base_evidence, {"freshness_status": "STALE"}),
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["stale_evidence"]
	result.obligations == [{"type": "refresh_evidence"}]
}

test_unknown_required_input_is_non_allow if {
	result := transfer_v2.result with input as {
		"parameters": {},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision != "allow"
	result.reasons == ["invalid_or_missing_required_input"]
}

# Same nominal scenario as v1's test_below_threshold_allowed (60 of 140,
# safety_stock 50) diverges under v2's LOWER approval threshold (80, not
# 100) once quantity crosses it — proven directly here rather than only via
# the live counterfactual reevaluate path.
test_v1_v2_threshold_divergence_documented if {
	result := transfer_v2.result with input as {
		"parameters": {"quantity": 90},
		"evidence": base_evidence,
		"config": base_config,
	}
	result.decision == "require_approval"
}
