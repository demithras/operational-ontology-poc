package factory.work_order.reschedule_test

import data.factory.work_order.reschedule

test_low_priority_allowed if {
	result := reschedule.result with input as {"evidence": {"work_order_status": "PLANNED", "priority": "LOW"}}
	result.decision == "allow"
}

test_high_priority_requires_approval if {
	result := reschedule.result with input as {"evidence": {"work_order_status": "PLANNED", "priority": "HIGH"}}
	result.decision == "require_approval"
	result.obligations == [{"type": "approval", "relation": "can_approve_large_transfer"}]
}

test_done_status_denied if {
	result := reschedule.result with input as {"evidence": {"work_order_status": "DONE", "priority": "LOW"}}
	result.decision == "deny"
	result.reasons == ["work_order_terminal"]
}

test_cancelled_status_denied if {
	result := reschedule.result with input as {"evidence": {"work_order_status": "CANCELLED", "priority": "HIGH"}}
	result.decision == "deny"
}

test_missing_input_is_non_allow if {
	result := reschedule.result with input as {"evidence": {}}
	result.decision != "allow"
}
