"""F36 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"unrelated concurrent stock receipt -> WMS -> reconciliation recognizes the
intended transfer correctly").

services/action_worker/outcome_eval.py::evaluate_transfer_outcome
deliberately evaluates success via the CORRELATED fac:WmsTransferRecord's
own `actual_quantity` (spec 06: "must use correlated transaction/transfer
facts rather than naive absolute arithmetic") rather than by diffing
`current_inventory`'s raw before/after available quantity — this test
proves that design choice actually matters: an unrelated stock receipt
lands on the SAME (part, warehouse) lot WHILE a governed transfer is
in flight, which would corrupt a naive "read current stock and subtract"
predicate but leaves the correlated one untouched.
"""

from __future__ import annotations

import httpx
import psycopg

from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait


def test_f36_unrelated_concurrent_stock_receipt_does_not_corrupt_outcome(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910901", "WH-B", on_hand=200)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 40)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision

    start_execution(decision_client, decision["decision_id"])

    # Simulate an UNRELATED external stock receipt at the SOURCE warehouse
    # WHILE the governed transfer may still be in flight — a real-world
    # event this decision never proposed or knows about (e.g. a physical
    # inbound delivery), applied directly via WMS's own test-mode exact-set
    # endpoint (same mechanism tests/integration/test_wms_concurrency.py
    # uses to set up known stock levels). A NAIVE "source.available_after
    # == source.available_before - q" predicate computed against a LATER
    # read of current_inventory would now be corrupted by this +500 bump;
    # the correlated-record predicate must not be.
    r = wms_client.post("/_test/inventory/set", json={"part": "SKU-910901", "warehouse_id": "WH-B", "on_hand": 700})
    assert r.status_code == 200, r.text

    final = wait_for_terminal_status(decision_client, decision["decision_id"])
    assert final["status"] == "OBSERVED_SUCCESS", final

    outcome_id = f"O-AX-{decision['decision_id']}"
    outcome = decision_client.get(f"/outcomes/{outcome_id}").json()
    assert outcome["reconciliationState"] == "CONVERGED", outcome

    transfer = wms_client.get(f"/transfers/AX-{decision['decision_id']}").json()
    assert transfer["status"] == "COMMITTED"
    assert transfer["actual_quantity"] == 40  # the correlated record, exactly the requested quantity

    # The unrelated receipt's own effect is real and observable too — this
    # is NOT "the receipt never happened", only "it never got attributed to
    # THIS transfer" (see tests/faults/test_manual_db_edit.py's F37 sibling
    # for the direct-DB-edit / attribution-provenance angle in more depth).
    # Two legitimate final values depending on which write actually landed
    # LAST at the database (genuinely concurrent, deliberately not
    # coordinated with the transfer — that IS the fault being injected):
    # 660 if this transfer's own -40 applied after the exact-set(700), or
    # 700 if the exact-set(700) overwrote a state that already reflected
    # the -40 deduction. Either is a correct, non-corrupted outcome; a
    # THIRD value would indicate double-counting or a lost update.
    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910901", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] in (660, 700), f"unexpected on_hand={lot['on_hand']} — neither race outcome, suggests corruption"
