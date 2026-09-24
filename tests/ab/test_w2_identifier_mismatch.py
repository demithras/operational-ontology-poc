"""W2 — cross-system identifier mismatch + a mapping change (spec 10).

Part 1: proves normal cross-system identity resolution already works for
both variants (three DIFFERENT source-local ids — ERP `PART-070xx`, MES
`COMP-070xx`, WMS `SKU-1070xx` — all resolve to the SAME canonical
`PX-70xx`, and each variant's evidence correctly reads inventory keyed by
the resolved canonical id, never a source-local one).

Part 2: "one mapping changes" — adds ONE new explicit-override entry to
`contracts/identity/v1/mapping_rules.yaml` (a SHARED contract file, read
by services/identity_resolver.IdentityResolver, reused verbatim by both
variants per this phase's central fairness decision — see
docs/experiment/implementation-notes.md Phase 8 item 1). Since both
variants' CDC consumers load this resolver ONCE at process startup (same
as the ontology variant always has), the ENGINEERING cost of "add a new
source identifier mapping" is measured directly from the git diff on this
ONE shared file — zero variant-specific code change either side, an
honest, tight H11 comparison point, not a live-restart demonstration.
`services/baseline/consumer.py` is separately restarted once to prove the
mechanism actually reaches a live consumer when it does restart (bounding
the real operational cost), without needing to also restart the ontology's
`ingestion` container (identical code path, restarting one is sufficient
evidence).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from services.identity_resolver.resolver import IdentityResolver, Quarantined, Resolved
from tests.ab import synthetic
from tests.ab.harness import Harness

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING_RULES_PATH = REPO_ROOT / "contracts" / "identity" / "v1" / "mapping_rules.yaml"
NEW_OVERRIDE_LOCAL_ID = "SKU-777777"  # deliberately outside the generated-index-v1 pattern's normal reach


def _part2_add_mapping_override(target_canonical_id: str) -> tuple[int, int]:
    """Appends one explicit_override rule mapping NEW_OVERRIDE_LOCAL_ID (WMS)
    to `target_canonical_id`. Returns (files_changed, lines_added) — the W2
    "effort to add a new source identifier mapping" measurement, taken from
    the raw text diff (no git commit needed to measure it: this file is
    small and the change is self-contained)."""
    original = MAPPING_RULES_PATH.read_text()
    if NEW_OVERRIDE_LOCAL_ID in original:
        return 0, 0  # already applied by a previous run of this workload
    addition = f"""
  # Phase 8 W2 (A/B experiment): one new source-identifier mapping, added
  # live to prove the identical mechanism/effort applies to both variants.
  - rule_id: ab-w2-mapping-change
    version: "1"
    kind: explicit_override
    authority: fixture-override
    confidence: 1.0
    comment: "tests/ab/test_w2_identifier_mismatch.py — synthetic mapping change."
    entries:
      - canonical_id: {target_canonical_id}
        source_ids:
          WMS: {NEW_OVERRIDE_LOCAL_ID}
"""
    MAPPING_RULES_PATH.write_text(original + addition)
    return 1, len(addition.strip().splitlines())


def _restart_baseline_ingestion() -> float:
    started = time.monotonic()
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build", "baseline_ingestion"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        env={**os.environ, "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", "")},
    )
    return time.monotonic() - started


def run(h: Harness) -> dict:
    # --- Part 1: normal cross-system identity resolution -----------------
    part = synthetic.part_ids(2)
    synthetic.ensure_erp_part(h.erp_conn, part)
    synthetic.set_wms_inventory(h.wms_http.base_url, part, "WH-B", on_hand=50)
    converged = synthetic.wait_both_converged(h.baseline_conn, h.ontology_hot_conn, part, "WH-B", 50, timeout_s=40.0)

    resolutions = {}
    for system, local_id in (("ERP", part.erp_id), ("MES", part.mes_id), ("WMS", part.wms_id)):
        result = IdentityResolver().resolve(system, local_id)
        resolutions[system] = {
            "local_id": local_id,
            "resolved_canonical": result.canonical_id if isinstance(result, Resolved) else None,
            "quarantined": isinstance(result, Quarantined),
        }
    all_resolve_to_same_canonical = len({r["resolved_canonical"] for r in resolutions.values()}) == 1

    decisions_part1 = {}
    for name, client in h.clients.items():
        resp = client.propose("transfer_inventory", "user", "planner-1", {
            "source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part.canonical_id, "quantity": 5,
        })
        decisions_part1[name] = resp.json().get("status")

    # --- Part 2: the mapping change ---------------------------------------
    files_changed, lines_added = _part2_add_mapping_override(part.canonical_id)

    # Mechanism proof: a FRESH resolver instance (same class both variants'
    # consumers use) picks up the new rule immediately — no code change,
    # config-file-only.
    fresh_result = IdentityResolver().resolve("WMS", NEW_OVERRIDE_LOCAL_ID)
    mechanism_resolves_correctly = isinstance(fresh_result, Resolved) and fresh_result.canonical_id == part.canonical_id

    # Live-consumer restart proof is DELIBERATELY NOT part of this
    # automated run (a container restart costs ~20-50s of consumer-group
    # rebalance — see docs/experiment/implementation-notes.md Phase 8 item 1's
    # "Operational note" — and re-running `make ab` should not pay that cost
    # every time). Verified manually ONCE during Phase 8 build instead; see
    # `verify_live_consumer_picks_up_mapping_change()` below and the
    # implementation notes for that run's recorded result.
    live_converged = None

    return {
        "workload": "W2_identifier_mismatch_and_mapping_change",
        "converged_before_mapping_change": converged,
        "resolutions": resolutions,
        "all_resolve_to_same_canonical": all_resolve_to_same_canonical,
        "decisions_part1": decisions_part1,
        "mapping_change_effort": {"files_changed": files_changed, "lines_added": lines_added, "shared_across_variants": True},
        "mechanism_resolves_correctly": mechanism_resolves_correctly,
        "live_consumer_picked_up_new_mapping": live_converged,  # see verify_live_consumer_picks_up_mapping_change()
        "part": part.canonical_id,
    }


def verify_live_consumer_picks_up_mapping_change(h: Harness, canonical_id: str) -> dict:
    """Standalone, NOT called by run()/pytest — run once by hand:

        .venv/bin/python -c "
        from tests.ab.harness import Harness
        from tests.ab.test_w2_identifier_mismatch import verify_live_consumer_picks_up_mapping_change
        h = Harness.create()
        print(verify_live_consumer_picks_up_mapping_change(h, 'PX-7002'))
        "

    Restarts baseline_ingestion (paying the real rebalance cost once,
    measured) and proves the SAME new mapping rule that a fresh in-process
    resolver already resolves correctly (run()'s mechanism_resolves_correctly)
    also reaches a genuinely restarted, long-running consumer — the
    "does this actually work operationally, not just in theory" half of W2.
    """
    import httpx

    restart_seconds = _restart_baseline_ingestion()
    with httpx.Client(base_url=h.wms_http.base_url, timeout=10.0) as wms:
        wms.post("/_test/inventory/set", json={"part": NEW_OVERRIDE_LOCAL_ID, "warehouse_id": "WH-C", "on_hand": 30, "reserved": 0, "quality_status": "OK"})
    part = synthetic.part_ids(2)
    live_converged = synthetic.wait_baseline_inventory(h.baseline_conn, part, "WH-C", 30, timeout_s=60.0)
    return {"baseline_ingestion_restart_seconds": restart_seconds, "live_consumer_picked_up_new_mapping": live_converged}


def test_w2_identifier_mismatch(harness: Harness):
    result = run(harness)
    assert result["converged_before_mapping_change"] == {"baseline": True, "ontology": True}, result
    assert result["all_resolve_to_same_canonical"], result
    assert result["decisions_part1"]["ontology"] == result["decisions_part1"]["baseline"], result
    assert result["mechanism_resolves_correctly"], result
