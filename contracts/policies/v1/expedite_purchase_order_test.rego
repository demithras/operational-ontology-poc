package factory.purchase_order.expedite_test

import data.factory.purchase_order.expedite

base_config := {"approval_threshold_cost": 500}

test_below_threshold_allowed if {
	result := expedite.result with input as {
		"parameters": {"expedite_fee": 100},
		"evidence": {"po_status": "OPEN"},
		"config": base_config,
	}
	result.decision == "allow"
}

test_above_threshold_requires_approval if {
	result := expedite.result with input as {
		"parameters": {"expedite_fee": 900},
		"evidence": {"po_status": "OPEN"},
		"config": base_config,
	}
	result.decision == "require_approval"
	result.obligations == [{"type": "approval", "relation": "can_approve_large_transfer"}]
}

test_terminal_status_denied if {
	result := expedite.result with input as {
		"parameters": {"expedite_fee": 100},
		"evidence": {"po_status": "RECEIVED"},
		"config": base_config,
	}
	result.decision == "deny"
	result.reasons == ["purchase_order_terminal"]
}

test_cancelled_status_denied if {
	result := expedite.result with input as {
		"parameters": {"expedite_fee": 100},
		"evidence": {"po_status": "CANCELLED"},
		"config": base_config,
	}
	result.decision == "deny"
}

test_missing_input_is_non_allow if {
	result := expedite.result with input as {"parameters": {}, "evidence": {}, "config": base_config}
	result.decision != "allow"
}
