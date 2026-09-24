"""F34 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"action definition changes post-approval -> runtime -> approved pinned
version executes or decision invalidated explicitly").

services/decision_service/propose_flow.py stamps
`oo:actionPinnedSha256` (from contracts/manifests/current.json's per-action
sha256, computed by services/decision_service/manifest.py at
decision_service's own process startup) onto every Decision.
services/action_worker/activities.py::verify_and_start_execution
re-hashes contracts/actions/v1/<name>.yaml FRESH off disk (never the
cached services/decision_service/action_types.py registry) and compares —
a mismatch moves the Decision straight to ACTION_VERSION_INVALIDATED,
never calling WMS at all.

The test mutates contracts/actions/v1/transfer_inventory.yaml ON DISK
(visible live inside the action_worker container via docker-compose.yml's
`./contracts:/app/contracts:ro` bind mount — see that file's own comment)
to a DIFFERENT byte sequence than what decision_service pinned at propose()
time (decision_service's own manifest is cached in-process at ITS startup,
so it keeps pinning the ORIGINAL hash regardless of this edit — exactly the
"action definition changes post-approval" scenario). The file is restored
in a `finally` block; nothing here survives past this one test.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx
import psycopg

from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait

REPO_ROOT = Path(__file__).resolve().parents[2]
# Phase 7: NOT hardcoded to v1 — this stack's deployed_version.json may
# have moved on to v2/v3 by the time this runs (migrations/v1_to_v2/,
# migrations/v2_to_v3/); a fresh decision proposed here pins whatever
# contracts/actions/<current>/transfer_inventory.yaml is CURRENTLY live,
# and this test must mutate that SAME file to stay a valid F34 repro.
from services.common.contract_versions import deployed_version  # noqa: E402

ACTION_VERSION_DIR = deployed_version()["actions"]
ACTION_YAML = REPO_ROOT / "contracts" / "actions" / ACTION_VERSION_DIR / "transfer_inventory.yaml"


def test_f34_action_definition_changed_post_approval_invalidates_never_executes(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910501", "WH-B", on_hand=150)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 20)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision
    assert decision["action_version_dir"] == ACTION_VERSION_DIR, (
        "this test computed its expected pin from a DIFFERENT actions/ directory "
        "than decision_service actually pinned — deployed_version.json moved between "
        "module import and this request"
    )

    pinned_sha256 = hashlib.sha256(ACTION_YAML.read_bytes()).hexdigest()
    assert decision["action_pinned_sha256"] == pinned_sha256, (
        "decision_service pinned a DIFFERENT sha256 than the file on disk right now — "
        "either the manifest logic or this test's assumption about decision_service's "
        "own startup-time cache is wrong"
    )

    original_bytes = ACTION_YAML.read_bytes()
    try:
        # A byte-for-byte different, but still syntactically valid, YAML —
        # appending a trailing comment changes the sha256 without breaking
        # anything that might re-parse the file (get_action_type's own
        # cached registry is untouched either way, by construction).
        ACTION_YAML.write_bytes(original_bytes + b"\n# Phase 6b F34 test: post-approval mutation\n")
        mutated_sha256 = hashlib.sha256(ACTION_YAML.read_bytes()).hexdigest()
        assert mutated_sha256 != pinned_sha256
        # Docker Desktop's bind-mount file-sharing (virtiofs/osxfs) has a
        # short (empirically ~1-2s) propagation delay between a host write
        # and that same content becoming visible via `docker exec` /
        # in-container reads — verified directly against this stack's
        # action_worker container before adding this sleep (a write visible
        # immediately on the host still read back as the OLD bytes from
        # inside the container with 0s delay, but consistently the NEW
        # bytes after 2s). Settle before triggering execute() so the
        # activity's fresh on-disk read is guaranteed to see the mutation.
        time.sleep(2.0)

        start_execution(decision_client, decision["decision_id"])
        final = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=30.0)
    finally:
        ACTION_YAML.write_bytes(original_bytes)
        # Give the (still-mounted, still-live) file a moment to be re-read
        # as the ORIGINAL bytes by any activity that might run again before
        # this test's decision reaches WMS — none should, but this keeps
        # the repo state and the container's view of it consistent before
        # the next test starts.
        time.sleep(0.2)

    assert final["status"] == "ACTION_VERSION_INVALIDATED", final

    # Zero external effect — WMS was never called at all (the mismatch is
    # caught in verify_and_start_execution, before call_external_action).
    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910501", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 150

    execution = decision_client.get(f"/executions/AX-{decision['decision_id']}")
    assert execution.status_code == 404, "no ActionExecution should ever have been written for an invalidated pin"
