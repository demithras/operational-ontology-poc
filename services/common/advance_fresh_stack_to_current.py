"""`make seed` (after wait-converged): a genuinely fresh stack (0 rows in
`decisions`, deployed_version.json still the tracked V1 baseline) is
automatically advanced to the CURRENT published contract state — TODAY
that is V1->V2->V3 — via the exact same real migration deploy() functions
`make deploy-v2`/`make deploy-v3`/`make deploy-v3-gates` already use.

Why here, not inside `make up`: migrations/v1_to_v2/deploy.py's own
migrate_rdf() operates on REAL ingested source facts (retiring
fac:availableQuantity triples asserted per inventory lot) — meaningless
before `make seed` has actually loaded and CDC-ingested any inventory
data. Running the cascade before that point would silently migrate 0
rows and prove nothing.

Orchestrator correction (Phase 10b, 2026-09-24): a genuinely fresh
clean-machine stack must serve the product's CURRENT deployed contracts by
default — `make test` is written throughout Phases 5-10 assuming V3
features are live, and README's own definition-of-done runs `make test`
directly after `make seed`, with no manual deploy-vN step in between. The
fair-evolution-comparison generators (docs/experiment/briefs/phase10b.md
item 7, scripts/gen_evolution_comparison.py) are the ones that now
EXPLICITLY descend back to the V1 genesis state when they need to build
V1-era history, then advance forward again the same way this module does.

Never fails `make seed` outright over an already-migrated stack: if the
freshness check says "not fresh" (real history already exists, or
freshness is undetermined), this is a silent, safe no-op — the whole
point is to advance a GENUINELY fresh stack exactly once, never to
re-apply a migration to a stack that already has it (migrations/*/deploy.py
are documented as "not idempotent-safe to re-run against a stack already
at v2+").
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.common.reset_deployed_version_if_empty import _decisions_table_is_empty  # noqa: E402


def _quiesce_projections(log=print, max_wait_s: float = 120.0, poll_s: float = 3.0) -> dict:
    """Root cause (orchestrator correction, Phase 10b, 2026-09-24): the
    first live run of this module hit `migrations/v1_to_v2/deploy.py`'s
    own before/after projection-hash check failing
    (work_order_risk/transfer_candidates/action_eligibility_summary
    mismatched; current_inventory matched) immediately after `make seed`'s
    wait-converged returned. wait-converged only proves Kafka CDC lag is 0
    and ONE canonical row (WO-42) exists in work_order_risk — it does NOT
    prove `services/projection_builder`'s own ~3s-interval LIVE POLL LOOP
    has finished rebuilding all 200 work orders'/1988 lots' rows from the
    now-fully-ingested RDF4J graph. `deploy_v2()`'s "before" snapshot is
    whatever the live loop had written by that exact moment — a moving
    target — while its "after" snapshot follows an EXPLICIT, complete
    rebuild; the two can legitimately differ by nothing more than "which
    poll cycle happened to be in flight when we looked."

    Proven live (diagnostic probe, same stack, ~14 minutes after seed had
    long since settled): calling build_all() twice in a row produces
    IDENTICAL hashes for all four tables, and matches the then-current
    live-poll-loop state too — the compute is fully deterministic once
    inputs stop changing; this was a timing race, not a migration
    correctness bug, and not a case for weakening the check.

    Fix: call build_all() (the SAME function the live poll loop and `make
    rebuild-projections` both use — see its own module docstring) directly
    here, in a loop, until TWO CONSECUTIVE calls produce identical
    business-field hashes for all four tables — the same fixed-point
    definition of "settled" wait_converged.py already uses for Kafka lag.
    Raises loudly (never silently proceeds) if quiescence isn't reached
    within max_wait_s — a genuinely non-converging projection pipeline is
    exactly the kind of thing that must not be papered over."""
    import psycopg
    from seed import db_env
    from services.common.rdf4j_client import RDF4JClient
    from services.projection_builder.builder import build_all
    from services.projection_builder.hashing import BUSINESS_COLUMNS, table_hash

    def table_hashes(conn) -> dict[str, str]:
        hashes = {}
        with conn.cursor() as cur:
            for table, cols in BUSINESS_COLUMNS.items():
                cur.execute(f"SELECT {', '.join(cols)} FROM {table}")  # noqa: S608 - fixed internal column list
                col_names = [d.name for d in cur.description]
                rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
                hashes[table] = table_hash(table, rows)
        return hashes

    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    rdf_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    t0 = time.monotonic()
    prev: dict[str, str] | None = None
    attempts = 0
    try:
        while True:
            attempts += 1
            build_all(rdf_client, conn)
            cur = table_hashes(conn)
            if prev is not None and cur == prev:
                elapsed = round(time.monotonic() - t0, 1)
                log(f"[advance_fresh_stack_to_current] projections quiesced after {attempts} build_all() "
                    f"calls ({elapsed}s) — two consecutive rebuilds produced identical business-field hashes")
                return {"quiesced": True, "attempts": attempts, "elapsed_s": elapsed}
            if time.monotonic() - t0 > max_wait_s:
                raise RuntimeError(
                    f"projections did not quiesce within {max_wait_s}s ({attempts} build_all() attempts) — "
                    f"last two hashes differed: {prev} vs {cur}"
                )
            prev = cur
            time.sleep(poll_s)
    finally:
        rdf_client.close()
        conn.close()


def advance_if_fresh(log=print) -> dict:
    if os.environ.get("OO_SKIP_AUTO_ADVANCE"):
        log("[advance_fresh_stack_to_current] OO_SKIP_AUTO_ADVANCE set — staying at the V1 genesis baseline "
            "(used by scripts/gen_evolution_comparison.py's own internal fresh-reset, which needs the REAL "
            "V1 SHACL shapes genuinely live to build V1-era history under real historical rules, not just a "
            "version-label pointer)")
        return {"advanced": False, "reason": "OO_SKIP_AUTO_ADVANCE set"}

    empty = _decisions_table_is_empty()
    if not empty:
        log("[advance_fresh_stack_to_current] decisions table has rows (or freshness undetermined) — "
            "stack already has real history, skipping auto-advance")
        return {"advanced": False, "reason": "not fresh"}

    log("[advance_fresh_stack_to_current] fresh stack detected (0 decisions) — advancing V1 -> V2 -> V3 "
        "(the product's current published contract state) via the real migration deploy() functions")

    log("[advance_fresh_stack_to_current] quiescing services/projection_builder before deploy-v2's own "
        "before/after hash check — wait-converged proves CDC lag is 0, not that the live poll loop has "
        "finished rebuilding every row from the now-fully-ingested graph")
    _quiesce_projections(log=log)

    from migrations.v1_to_v2.deploy import deploy as deploy_v2
    from migrations.v2_to_v3.deploy import deploy as deploy_v3
    from migrations.v2_to_v3_gates.deploy import deploy as deploy_v3_gates

    v2_result = deploy_v2()
    log(f"[advance_fresh_stack_to_current] deploy-v2 done: {v2_result.get('deployed_version_after')}")
    if not all(v2_result.get("rebuild_hash_matches", {}).values()):
        raise RuntimeError(f"deploy-v2 projection rebuild hash mismatch during auto-advance: {v2_result}")

    v3_result = deploy_v3()
    log(f"[advance_fresh_stack_to_current] deploy-v3 done: {v3_result.get('deployed_version_after')}")

    gates_result = deploy_v3_gates()
    log(f"[advance_fresh_stack_to_current] deploy-v3-gates done: {gates_result.get('deployed_version_after')}")

    return {
        "advanced": True,
        "deploy_v2": v2_result, "deploy_v3": v3_result, "deploy_v3_gates": gates_result,
        "final_deployed_version": gates_result.get("deployed_version_after"),
    }


def main() -> int:
    result = advance_if_fresh()
    if result["advanced"]:
        print(f"[advance_fresh_stack_to_current] final deployed_version.json: {result['final_deployed_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
