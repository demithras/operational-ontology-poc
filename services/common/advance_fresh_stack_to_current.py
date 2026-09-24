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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.common.reset_deployed_version_if_empty import _decisions_table_is_empty  # noqa: E402


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
