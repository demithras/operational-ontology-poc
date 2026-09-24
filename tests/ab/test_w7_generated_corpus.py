"""W7 — generated incident corpus (spec 10: "500-1000 incident sequences").

Seeds N independent, synthetic `transfer_inventory` scenarios (tests/ab/generator.py,
deterministic from SEED) through the real ERP/WMS APIs/DB, waits once for
both CDC pipelines to settle, then proposes each scenario to BOTH variants
and records: decision match between variants, and decision match against
the reference_model oracle (every W7 scenario uses `reserved=0`, so the
oracle applies exactly — see tests/ab/oracle.py's own documented scope).

N defaults to 500 (the spec's floor) — override via `OO_AB_W7_N` for a
smaller smoke run. This workload is the one place in tests/ab that is
SLOW by design (hundreds of real propose() calls against a live stack);
it is intentionally excluded from `pytest tests/ab` at default settings'
plain run cost and instead driven primarily by `scripts/run_ab.py`/`make ab`
— see that script for how it is invoked with a full N.
"""

from __future__ import annotations

import os
import time

from tests.ab import generator, oracle, synthetic
from tests.ab.harness import Harness

DEFAULT_N = 500
DEFAULT_SEED = 20260924


def seed_all(h: Harness, scenarios: list[generator.Scenario]) -> None:
    for s in scenarios:
        part = synthetic.part_ids(s.index)
        synthetic.ensure_erp_part(h.erp_conn, part)
        if s.seed_inventory:
            synthetic.set_wms_inventory(h.wms_http.base_url, part, s.source_warehouse, on_hand=s.on_hand, reserved=0, quality_status=s.quality_status)


def run(h: Harness, n: int = DEFAULT_N, seed: int = DEFAULT_SEED, settle_s: float | None = None) -> dict:
    scenarios = generator.generate(n, seed)
    t_seed_start = time.monotonic()
    seed_all(h, scenarios)
    seed_elapsed = time.monotonic() - t_seed_start
    # Found live during Phase 8 build: a fixed 5s settle was NOT enough
    # margin for the ontology variant's CDC -> RDF4J -> projection_builder
    # pipeline (its own ~3s poll cycle) to fully catch up on a BURST of N
    # distinct synthetic parts seeded in quick succession — the first
    # several propose() calls then hit evidence.py's internal freshness
    # retry (up to 8s/10 attempts) repeatedly, inflating p95 latency to
    # several SECONDS (a measurement artifact of insufficient settle time,
    # not a real architectural cost — verified: with settle_s=8, the same
    # scenarios propose in ~50-65ms each, matching the documented "warm"
    # bench-phase5.json figure). Scales with N since more distinct parts
    # means more catch-up work either pipeline must do.
    if settle_s is None:
        settle_s = max(10.0, n * 0.05)
    time.sleep(settle_s)  # let both CDC pipelines drain the seeding burst

    results = []
    latencies_s: dict[str, list[float]] = {"ontology": [], "baseline": []}
    t_propose_start = time.monotonic()
    for s in scenarios:
        part = synthetic.part_ids(s.index)
        params = {"source_warehouse": s.source_warehouse, "destination_warehouse": s.destination_warehouse, "part": part.canonical_id, "quantity": s.quantity}
        per_variant = {}
        for name, client in h.clients.items():
            t0 = time.monotonic()
            resp = client.propose("transfer_inventory", "user", s.actor_id, params)
            latencies_s[name].append(time.monotonic() - t0)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            per_variant[name] = body.get("status") or f"HTTP_{resp.status_code}"

        oracle_status = None
        oracle_reason = None
        if s.seed_inventory and not s.skip_oracle:
            oracle_status, oracle_reason = oracle.expected_transfer_status(
                part.canonical_id, s.source_warehouse, s.destination_warehouse, s.quantity, s.actor_id,
                source_on_hand=s.on_hand, source_quality=s.quality_status,
            )

        results.append({
            "seq": s.seq, "bucket": s.expected_class, "part": part.canonical_id,
            "decisions": per_variant,
            "variants_match": per_variant.get("ontology") == per_variant.get("baseline"),
            "oracle_status": oracle_status,
            "ontology_matches_oracle": (oracle_status is not None) and per_variant.get("ontology") == oracle_status,
            "baseline_matches_oracle": (oracle_status is not None) and per_variant.get("baseline") == oracle_status,
        })
    propose_elapsed = time.monotonic() - t_propose_start

    n_total = len(results)
    n_variants_match = sum(1 for r in results if r["variants_match"])
    oracle_checked = [r for r in results if r["oracle_status"] is not None]
    n_ontology_oracle_match = sum(1 for r in oracle_checked if r["ontology_matches_oracle"])
    n_baseline_oracle_match = sum(1 for r in oracle_checked if r["baseline_matches_oracle"])

    status_distribution = {"ontology": {}, "baseline": {}}
    for r in results:
        for variant in ("ontology", "baseline"):
            st = r["decisions"].get(variant)
            status_distribution[variant][st] = status_distribution[variant].get(st, 0) + 1

    mismatches = [r for r in results if not r["variants_match"]][:25]  # cap for report size

    def _p95(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    return {
        "workload": "W7_generated_incident_corpus",
        "n": n_total, "seed": seed,
        "seed_elapsed_s": seed_elapsed, "propose_elapsed_s": propose_elapsed,
        "variants_decision_match_rate": n_variants_match / n_total if n_total else None,
        "oracle_checked_count": len(oracle_checked),
        "ontology_oracle_match_rate": n_ontology_oracle_match / len(oracle_checked) if oracle_checked else None,
        "baseline_oracle_match_rate": n_baseline_oracle_match / len(oracle_checked) if oracle_checked else None,
        "status_distribution": status_distribution,
        "sample_mismatches": mismatches,
        "proposal_latency_p95_ms": {name: (_p95(vals) * 1000 if _p95(vals) is not None else None) for name, vals in latencies_s.items()},
        "proposal_latency_mean_ms": {name: (sum(vals) / len(vals) * 1000 if vals else None) for name, vals in latencies_s.items()},
    }


def test_w7_generated_corpus_smoke(harness: Harness):
    """A FAST smoke run (small N) for `pytest tests/ab` / CI — the FULL
    500+ run is driven by scripts/run_ab.py, not by default pytest
    collection (see module docstring)."""
    n = int(os.environ.get("OO_AB_W7_SMOKE_N", "15"))
    result = run(harness, n=n, seed=DEFAULT_SEED)
    assert result["n"] == n
    assert result["variants_decision_match_rate"] == 1.0, result["sample_mismatches"]
    if result["oracle_checked_count"]:
        assert result["ontology_oracle_match_rate"] == 1.0, result["sample_mismatches"]
        assert result["baseline_oracle_match_rate"] == 1.0, result["sample_mismatches"]
