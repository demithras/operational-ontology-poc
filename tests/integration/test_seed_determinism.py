"""docs/experiment/briefs/phase2.md item 3: "The same seed must give the
same loaded state (prove it with a sha256 over sorted WMS lots via the API,
across two reset+seed runs)."

This test performs its own `make reset && make seed` TWICE (it is the one
integration test allowed to tear down and rebuild the stack) and hashes the
loaded WMS inventory_lots via the real HTTP API both times. Only business
fields are hashed (lot_id/part/warehouse_id/on_hand/reserved/quality_status)
— updated_at/version are wall-clock/audit fields that legitimately differ
run to run even when the business dataset is byte-identical.

Slow (two full reset+rebuild+reseed cycles, ~1-3 minutes). Runs as part of
`make test-integration` per the brief, not skipped by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402

BUSINESS_FIELDS = ("lot_id", "part", "warehouse_id", "on_hand", "reserved", "quality_status")

# Phase 9 step 0a (orchestrator finding from the Phase 8 review): this is
# the one test in the whole suite that tears the shared stack down and
# rebuilds it (`make reset` TWICE, via subprocess). Makefile's own
# `test-integration` target already `--ignore`s this file, but a plain
# `pytest tests/integration` (the whole directory, no Makefile) bypasses
# that ignore entirely and silently wipes whatever historical corpus was
# loaded — exactly what happened reviewing Phase 8. The guard now lives in
# the test itself, not only in the Makefile wiring around it: this test
# SKIPS unless OO_ALLOW_DESTRUCTIVE=1 is set, which only `make
# test-destructive` sets (see Makefile) — so no plain pytest invocation,
# from any directory or working style, can ever destroy data again.
pytestmark = pytest.mark.destructive


def _hash_wms_lots(client: httpx.Client) -> str:
    lots = client.get("/inventory_lots").json()
    business = sorted(({f: lot[f] for f in BUSINESS_FIELDS} for lot in lots), key=lambda r: r["lot_id"])
    return hashlib.sha256(json.dumps(business, sort_keys=True).encode("utf-8")).hexdigest()


def _reset_and_seed(seed: int) -> None:
    subprocess.run(["make", "reset"], cwd=REPO_ROOT, check=True, timeout=300)
    subprocess.run(["make", "seed", f"SEED={seed}"], cwd=REPO_ROOT, check=True, timeout=300)


def test_same_seed_gives_same_loaded_wms_state(stack_up: bool):
    if os.environ.get("OO_ALLOW_DESTRUCTIVE") != "1":
        pytest.skip(
            "destructive test (runs 'make reset' twice, wiping the shared stack incl. any historical "
            "corpus) — set OO_ALLOW_DESTRUCTIVE=1 to run it explicitly, or use 'make test-destructive', "
            "which sets that for you and is documented as needing to run ALONE"
        )
    if not stack_up:
        pytest.skip("stack not reachable — run 'make up' first (this test performs its own reset+reseed)")

    db_env.load_dotenv()
    base_url = db_env.http_base_urls()["wms"]
    long_timeout = httpx.Timeout(30.0)

    _reset_and_seed(42)
    with httpx.Client(base_url=base_url, timeout=long_timeout) as client:
        hash_run_1 = _hash_wms_lots(client)
        lot_count_1 = len(client.get("/inventory_lots").json())

    _reset_and_seed(42)
    with httpx.Client(base_url=base_url, timeout=long_timeout) as client:
        hash_run_2 = _hash_wms_lots(client)
        lot_count_2 = len(client.get("/inventory_lots").json())

    assert lot_count_1 == lot_count_2 > 0
    assert hash_run_1 == hash_run_2, "same SEED must produce a byte-identical loaded WMS business dataset"
