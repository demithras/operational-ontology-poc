"""docs/experiment/spec/09_failure_and_adversarial_matrix.md "Concurrency
tests" — the canonical race: initial stock 100, two decisions each want 80,
proposed independently (both legitimately APPROVED from the SAME snapshot —
"Both decisions may initially be proposed from the same evidence"), then
EXECUTED CONCURRENTLY. Forbidden: negative stock. Allowed: one success +
one rejection/re-evaluation — WMS's own row-level locking
(services/wms/transfers.py) serializes the two real transfers; the loser
sees insufficient stock and gets a REAL FAILED transfer record (0 effect),
which services/action_worker's outcome predicate correctly resolves to
EXECUTION_FAILED, never a fabricated success and never negative inventory.
"""

from __future__ import annotations

import threading

import httpx
import psycopg

from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait


def test_100_80_80_concurrent_execution_never_goes_negative_one_succeeds(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910401", "WH-B", on_hand=100)

    # planner-1 and junior-1 both hold can_transfer_inventory on WH-B
    # (contracts/authorization/v1/tuples.yaml) — supervisor-1 does NOT
    # (supervisor's only relation is can_approve_large_transfer), so two
    # INDEPENDENT actors who can each legitimately propose this transfer.
    decision_a = approve_if_needed(decision_client, propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 80))
    decision_b = approve_if_needed(decision_client, propose_transfer(decision_client, "junior-1", "WH-B", "WH-A", part, 80))
    assert decision_a["status"] == "APPROVED", decision_a
    assert decision_b["status"] == "APPROVED", decision_b

    results: dict[str, dict] = {}

    def _execute(label: str, decision_id: str):
        with httpx.Client(base_url=str(decision_client.base_url), timeout=15.0) as c:
            c.post(f"/decisions/{decision_id}/execute")
        results[label] = wait_for_terminal_status(decision_client, decision_id)

    t_a = threading.Thread(target=_execute, args=("A", decision_a["decision_id"]))
    t_b = threading.Thread(target=_execute, args=("B", decision_b["decision_id"]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=60)
    t_b.join(timeout=60)

    assert set(results) == {"A", "B"}

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910401", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] >= 0, "FORBIDDEN: negative inventory"
    assert lot["on_hand"] == 20, f"expected exactly one 80-unit transfer to have committed (100-80=20), got on_hand={lot['on_hand']}"

    success_count = sum(1 for s in (results["A"]["status"], results["B"]["status"]) if s == "OBSERVED_SUCCESS")
    assert success_count == 1, f"expected EXACTLY one success (never zero, never two silent successes with only 100 to share), got {results}"
    loser_status = next(s for label, s in (("A", results["A"]["status"]), ("B", results["B"]["status"])) if s != "OBSERVED_SUCCESS")
    assert loser_status in ("EXECUTION_FAILED", "DIVERGED"), (
        f"the losing decision must be a real, explicit non-success (never a fabricated ambiguous state), got {results}"
    )
