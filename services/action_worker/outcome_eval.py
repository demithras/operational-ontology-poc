"""Pure outcome-predicate evaluation — docs/experiment/spec/06_decision_and_action_runtime.md
"Outcome predicate" / "World divergence". No I/O here at all (mirrors
services/projection_builder/compute.py's own "pure computation" module
convention) so it is trivially unit-testable and so
services/action_worker/activities.py (the real Temporal-driven path) and
services/reconciliation (the independent re-check, H12) can call the EXACT
SAME function rather than two hand-written copies of the same predicate
drifting apart.

transfer_inventory gets the full, spec-exact predicate:

    source.available_after   == source.available_before - q
    destination.available_after == destination.available_before + q
    AND a WMS transfer record exists for action_execution_id

— evaluated via the CORRELATED fac:WmsTransferRecord (actual_quantity),
never naive "read current stock and subtract" (spec 06: "If another
legitimate concurrent event changes stock, the predicate must use
correlated transaction/transfer facts rather than naive absolute
arithmetic" — F36).

expedite_purchase_order / reschedule_work_order get a LIGHTER predicate
(documented scope decision, same precedent as Phase 5's lighter treatment
of these two ActionTypes): the external system's own idempotent command
response IS the ground truth (ERP/MES commit synchronously, no eventual-CDC
story to correlate against), so "observation" is the command result itself,
not a separate CDC poll.
"""

from __future__ import annotations

from dataclasses import dataclass


OBSERVED_SUCCESS = "OBSERVED_SUCCESS"
DIVERGED = "DIVERGED"
OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
EXECUTION_FAILED = "EXECUTION_FAILED"


@dataclass(frozen=True)
class OutcomeVerdict:
    status: str  # one of the four module-level constants above
    expected_effect: dict
    observed_effect: dict
    reason: str


def evaluate_transfer_outcome(
    requested_quantity: int,
    source_available_before: int,
    destination_available_before: int,
    transfer_record: dict | None,
) -> OutcomeVerdict:
    """`transfer_record` is the CDC-correlated fac:WmsTransferRecord for this
    action_execution_id (None if not observed within the contract's
    observation.timeout, PT30S — F18/F21)."""
    expected = {
        "requested_quantity": requested_quantity,
        "source_available_after_expected": source_available_before - requested_quantity,
        "destination_available_after_expected": destination_available_before + requested_quantity,
    }
    if transfer_record is None:
        return OutcomeVerdict(
            OUTCOME_UNKNOWN, expected, {},
            "no correlated WMS transfer record observed within the observation timeout (F18/F21)",
        )

    status = transfer_record.get("status")
    actual_quantity = int(transfer_record.get("actual_quantity", 0))
    observed = {
        "wms_transfer_status": status,
        "actual_quantity": actual_quantity,
        "source_available_after_observed": source_available_before - actual_quantity,
        "destination_available_after_observed": destination_available_before + actual_quantity,
    }

    if status == "FAILED":
        # F15: a WMS transfer row exists (idempotency-key-created) but
        # committed nothing — never OBSERVED_SUCCESS, and there is no
        # effect at all to diverge from, so EXECUTION_FAILED (not DIVERGED).
        return OutcomeVerdict(EXECUTION_FAILED, expected, observed, "WMS transfer record status=FAILED (0 effect)")

    if status in ("COMMITTED", "PARTIAL", "REVERSED") and actual_quantity != requested_quantity:
        # F16 (partial commit) / F17 (wrong quantity) — both are the SAME
        # observable shape (actual != requested) from this predicate's point
        # of view; the distinction is in `status`, preserved in observed_effect.
        return OutcomeVerdict(
            DIVERGED, expected, observed,
            f"WMS committed {actual_quantity} of {requested_quantity} requested (status={status})",
        )

    if status == "COMMITTED" and actual_quantity == requested_quantity:
        return OutcomeVerdict(OBSERVED_SUCCESS, expected, observed, "WMS transfer committed the exact requested quantity")

    # Any other status value is a genuinely unresolvable shape — fail to the
    # explicit-unknown state rather than guess (acceptance criterion 11).
    return OutcomeVerdict(OUTCOME_UNKNOWN, expected, observed, f"unrecognized WMS transfer status {status!r}")


def evaluate_command_response_outcome(action_type: str, http_status: int, response_body: dict) -> OutcomeVerdict:
    """Lighter predicate for expedite_purchase_order/reschedule_work_order —
    see module docstring. The command response itself (ERP/MES's own
    idempotent, synchronously-committed result) is the observation."""
    expected = {"action_type": action_type, "expected": "external system applies the requested change synchronously"}
    observed = {"http_status": http_status, "response_body": response_body}
    if http_status == 200:
        return OutcomeVerdict(OBSERVED_SUCCESS, expected, observed, f"{action_type} command committed (HTTP 200)")
    if http_status == 409:
        return OutcomeVerdict(
            EXECUTION_FAILED, expected, observed, f"{action_type} command rejected (HTTP 409 — terminal state or conflict)",
        )
    return OutcomeVerdict(OUTCOME_UNKNOWN, expected, observed, f"{action_type} command returned unexpected HTTP {http_status}")
