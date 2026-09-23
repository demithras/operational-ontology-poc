#!/usr/bin/env python3
"""Deterministic seed dataset generator — `make seed`.

Given the same SEED, always produces byte-identical output (verified by
sha256 of the generated files). Dataset volume targets are the ones locked
in experiments/exp-000/manifest.yaml (`dataset_sizes`), themselves taken
from docs/experiment/spec/02_scope_and_non_goals.md "Data volume target".

This generator produces a *business dataset* only (suppliers, parts,
purchase orders, warehouses, inventory lots, work orders, production
lines) — it does not touch the reference model, contracts, or any service.
Its purpose in Phase 1 is (a) proving the "same seed => same dataset"
determinism contract from
docs/experiment/spec/13_repository_contract.md and (b) providing a large,
non-trivially-hardcodable corpus for later phases to load into the fake
ERP/MES/WMS (Phase 2) and semantic core (Phase 3).

Output goes to seed/out/ (gitignored, regenerated on demand), as one JSON
file per entity type plus a manifest.json with the sha256 of the whole
output tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "seed" / "out"

DATASET_SIZES = {
    "suppliers": 20,
    "parts": 500,
    "purchase_orders": 2000,
    "warehouses": 4,
    "inventory_lots": 10000,
    "work_orders": 200,
    "production_lines": 8,
}

RISK_CLASSES = ["LOW", "MEDIUM", "HIGH"]
CRITICALITY = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
REGIONS = ["region-1", "region-2", "region-3", "region-4"]
CAPACITY_CLASSES = ["SMALL", "MEDIUM", "LARGE"]
WORK_ORDER_STATUSES = ["PLANNED", "RELEASED", "RUNNING", "DONE", "CANCELLED"]
WORK_ORDER_PRIORITIES = ["LOW", "MEDIUM", "HIGH"]
QUALITY_STATUSES = ["OK", "QUARANTINE"]
PO_STATUSES = ["OPEN", "DELAYED", "RECEIVED", "CANCELLED"]


def generate(seed: int) -> dict:
    rng = random.Random(seed)

    suppliers = [
        {
            "supplier_id": f"SUP-{i:04d}",
            "name": f"Supplier {i}",
            "status": rng.choice(["ACTIVE", "ACTIVE", "ACTIVE", "SUSPENDED"]),
            "lead_time_days": rng.randint(1, 45),
            "risk_class": rng.choice(RISK_CLASSES),
        }
        for i in range(DATASET_SIZES["suppliers"])
    ]

    parts = [
        {
            "canonical_part_id": f"PX-{i:04d}",
            "description": f"Part {i}",
            "unit": "each",
            "criticality": rng.choice(CRITICALITY),
            "source_identity_map": {
                "ERP": f"PART-{i:05d}",
                "MES": f"COMP-{i:05d}",
                "WMS": f"SKU-{100000 + i}",
            },
        }
        for i in range(DATASET_SIZES["parts"])
    ]

    warehouses = [
        {"warehouse_id": f"WH-{chr(ord('A') + i)}", "capacity_class": rng.choice(CAPACITY_CLASSES), "region": rng.choice(REGIONS)}
        for i in range(DATASET_SIZES["warehouses"])
    ]

    production_lines = [
        {
            "line_id": f"LINE-{i:02d}",
            "status": rng.choice(["ACTIVE", "ACTIVE", "MAINTENANCE"]),
            "capabilities": rng.sample([p["canonical_part_id"] for p in parts], k=min(5, len(parts))),
        }
        for i in range(DATASET_SIZES["production_lines"])
    ]

    purchase_orders = [
        {
            "po_id": f"PO-{i:05d}",
            "supplier_id": rng.choice(suppliers)["supplier_id"],
            "status": rng.choice(PO_STATUSES),
            "promised_at": rng.randint(0, 400),
            "expected_at": rng.randint(0, 800),
            "lines": [
                {
                    "part": rng.choice(parts)["canonical_part_id"],
                    "qty": rng.randint(1, 500),
                    "destination_warehouse": rng.choice(warehouses)["warehouse_id"],
                }
            ],
        }
        for i in range(DATASET_SIZES["purchase_orders"])
    ]

    inventory_lots = [
        {
            "lot_id": f"LOT-{i:06d}",
            "part": rng.choice(parts)["canonical_part_id"],
            "warehouse": rng.choice(warehouses)["warehouse_id"],
            "on_hand": rng.randint(0, 1000),
            "reserved": 0,
            "quality_status": rng.choices(QUALITY_STATUSES, weights=[95, 5])[0],
            "as_of": 0,
        }
        for i in range(DATASET_SIZES["inventory_lots"])
    ]
    # reserved must never exceed on_hand
    for lot in inventory_lots:
        lot["reserved"] = rng.randint(0, lot["on_hand"])

    work_orders = [
        {
            "work_order_id": f"WO-{i:04d}",
            "production_line": rng.choice(production_lines)["line_id"],
            "status": rng.choice(WORK_ORDER_STATUSES),
            "priority": rng.choice(WORK_ORDER_PRIORITIES),
            "planned_start": rng.randint(0, 400),
            "planned_finish": rng.randint(400, 800),
            "requirements": {rng.choice(parts)["canonical_part_id"]: rng.randint(1, 200)},
            "warehouse": rng.choice(warehouses)["warehouse_id"],
        }
        for i in range(DATASET_SIZES["work_orders"])
    ]

    return {
        "seed": seed,
        "suppliers": suppliers,
        "parts": parts,
        "warehouses": warehouses,
        "production_lines": production_lines,
        "purchase_orders": purchase_orders,
        "inventory_lots": inventory_lots,
        "work_orders": work_orders,
    }


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_dataset(dataset: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entity_files = [k for k in dataset.keys() if k != "seed"]
    hashes = {}
    for key in entity_files:
        path = out_dir / f"{key}.json"
        # sort_keys=True + fixed separators -> byte-identical output for
        # the same seed, independent of dict insertion-order quirks.
        path.write_text(json.dumps(dataset[key], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        hashes[key] = sha256_of_file(path)

    manifest = {
        "seed": dataset["seed"],
        "counts": {k: len(dataset[k]) for k in entity_files},
        "sha256": hashes,
    }
    combined = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    manifest["combined_sha256"] = combined
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "42")))
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    dataset = generate(args.seed)
    manifest = write_dataset(dataset, args.out)

    print(f"seed={manifest['seed']}")
    print(f"counts={json.dumps(manifest['counts'], sort_keys=True)}")
    print(f"combined_sha256={manifest['combined_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
