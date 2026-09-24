"""Three related spec 09 adversarial scenarios that don't fit the pure
"malicious tool argument" shape of the other files in this package:

1. Stale-decision execution — an agent tries `execute_approved_decision`
   on a decision that was never actually approved (this repo's reading of
   "stale": the agent treats its own proposal as if approval already
   happened, or happened for a decision that has since moved on).
2. F33 "approval replay on a changed decision" — approving with a hash
   that doesn't match the CURRENT decision. Not an MCP tool (there is no
   `approve` tool at all — see tests/agent/test_f04_undisclosed_tools.py),
   so this drives decision_service's raw HTTP endpoint directly: a
   compromised agent is not assumed to be MCP-obedient, and F31's own
   matrix entry is "MCP/action API" together, not MCP alone.
3. "Change the evidence snapshot to the newest one but keep the approval"
   — proven structurally: services/decision_service/hashing.py's
   `decision_content_hash` takes `evidence_snapshot_id` as a hashed input,
   so no two decisions can share a decision_content_hash while differing
   in evidence_snapshot_id. Since F33's own check rejects any approval
   whose supplied hash doesn't match the CURRENT decision's
   decision_content_hash, and evidence is frozen at propose() time with no
   API to mutate an existing decision's evidence_snapshot_id at all
   (propose() always mints a brand-new decision_id + evidence_snapshot_id
   together), there is no live action to attempt here beyond re-proving
   that premise — done via two independent live proposals.
"""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

from tests.agent.helpers import call_tool, inventory_unchanged, set_inventory_and_wait


def test_stale_decision_execution_rejected(
    mcp_server_granted: FastMCP, wms_client: httpx.Client, ontology_hot_conn, granted_warehouse: str
):
    """The agent proposes, gets an ALLOW-shaped small transfer that goes
    straight to APPROVED (no human step needed under threshold) — but a
    genuinely SEPARATE, never-approved decision (this test's real target)
    must still refuse execute()."""
    sku = "SKU-900830"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, granted_warehouse, on_hand=500)

    # A REQUIRES_APPROVAL decision (over threshold) — genuinely never
    # approved by anyone. "Stale" in the sense this test proves: no
    # approval event exists for it, ever, at any point in its lifetime.
    proposed = call_tool(
        mcp_server_granted,
        "propose_transfer_inventory",
        {"source_warehouse": granted_warehouse, "destination_warehouse": "WH-A", "part": part, "quantity": 200},
    )
    assert proposed["status"] == "REQUIRES_APPROVAL"
    decision_id = proposed["decision_id"]

    result = call_tool(mcp_server_granted, "execute_approved_decision", {"decision_id": decision_id})
    assert result.get("status_code") == 409, f"execute on a never-approved decision must be rejected: {result}"
    assert inventory_unchanged(wms_client, sku, granted_warehouse, 500)


def test_f33_approval_replay_with_stale_hash_rejected(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn, granted_warehouse: str
):
    sku = "SKU-900831"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, granted_warehouse, on_hand=500)

    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {"source_warehouse": granted_warehouse, "destination_warehouse": "WH-A", "part": part, "quantity": 200},
        },
    )
    decision = r.json()
    assert decision["status"] == "REQUIRES_APPROVAL"
    real_hash = decision["decision_content_hash"]
    stale_hash = ("0" if real_hash[0] != "0" else "1") + real_hash[1:]

    approve = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": stale_hash},
    )
    assert approve.status_code == 409, f"a stale/tampered decision_content_hash must be rejected (F33): {approve.text}"

    # The REAL hash still works — proves the rejection above was about the
    # hash mismatch specifically, not a broken approval path.
    approve_real = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": real_hash},
    )
    assert approve_real.status_code == 200, approve_real.text
    assert inventory_unchanged(wms_client, sku, granted_warehouse, 500), "approval alone (no execute) must cause zero WMS effects"


def test_evidence_snapshot_cannot_be_swapped_while_keeping_the_approval_hash(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn, granted_warehouse: str
):
    """Two independently-proposed decisions with IDENTICAL actor/action/
    parameters/contract-versions necessarily get DIFFERENT
    evidence_snapshot_id (propose() mints a fresh one every call) and
    therefore DIFFERENT decision_content_hash — proving live that
    decision B's approval hash can never validate against decision A (i.e.
    "keep the approval, swap the evidence" has no live payload to submit:
    the approval IS bound to one specific evidence_snapshot_id via the
    hash, structurally, not by a runtime check that could be raced)."""
    sku = "SKU-900832"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, granted_warehouse, on_hand=500)
    body = {
        "action_type": "transfer_inventory",
        "actor": {"type": "user", "id": "planner-1"},
        "parameters": {"source_warehouse": granted_warehouse, "destination_warehouse": "WH-A", "part": part, "quantity": 200},
    }

    decision_a = decision_client.post("/decisions/propose", json=body).json()
    decision_b = decision_client.post("/decisions/propose", json=body).json()
    assert decision_a["status"] == decision_b["status"] == "REQUIRES_APPROVAL"
    assert decision_a["evidence_snapshot_id"] != decision_b["evidence_snapshot_id"]
    assert decision_a["decision_content_hash"] != decision_b["decision_content_hash"], (
        "identical actor/action/parameters but different evidence snapshots must never collide on decision_content_hash"
    )

    # decision B's approval hash against decision A's id — the exact "keep
    # the approval, swap the evidence" attack, attempted directly.
    cross_approve = decision_client.post(
        f"/decisions/{decision_a['decision_id']}/approve",
        json={"approver_id": "supervisor-1", "decision_content_hash": decision_b["decision_content_hash"]},
    )
    assert cross_approve.status_code == 409, cross_approve.text
    assert inventory_unchanged(wms_client, sku, granted_warehouse, 500)
