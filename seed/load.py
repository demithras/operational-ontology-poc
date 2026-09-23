#!/usr/bin/env python3
"""Loads seed/out/*.json (from seed/generators/generate.py) plus
seed/fixtures/canonical_incident.yaml into the running ERP/MES/WMS Postgres
databases — each via that system's OWN role credentials, no cross-database
access — and writes seed/out/identity_truth.json.

Run via `make seed` (which runs generate.py first, then this script), or
directly:

    .venv/bin/python seed/load.py --seed 42

Requires the stack to be up (`make up`) and reachable at the host-mapped
Postgres port (POSTGRES_HOST_PORT in .env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from seed.identity import compute_identity  # noqa: E402
from seed.loaders import erp as erp_loader  # noqa: E402
from seed.loaders import mes as mes_loader  # noqa: E402
from seed.loaders import wms as wms_loader  # noqa: E402

OUT_DIR = REPO_ROOT / "seed" / "out"
CANONICAL_FIXTURE = REPO_ROOT / "seed" / "fixtures" / "canonical_incident.yaml"


def _load_json(name: str) -> Any:
    return json.loads((OUT_DIR / f"{name}.json").read_text())


def load_dataset() -> dict[str, Any]:
    return {
        "suppliers": _load_json("suppliers"),
        "parts": _load_json("parts"),
        "warehouses": _load_json("warehouses"),
        "production_lines": _load_json("production_lines"),
        "purchase_orders": _load_json("purchase_orders"),
        "inventory_lots": _load_json("inventory_lots"),
        "work_orders": _load_json("work_orders"),
    }


def build_parts_local(identity_records: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    return {rec["canonical_part_id"]: {"ERP": rec["ERP"], "MES": rec["MES"], "WMS": rec["WMS"]} for rec in identity_records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "42")))
    args = parser.parse_args(argv)

    db_env.load_dotenv()

    if not OUT_DIR.exists() or not (OUT_DIR / "manifest.json").exists():
        print("seed/out/ is missing — run `make seed` (which runs generate.py first) or "
              "`.venv/bin/python seed/generators/generate.py --seed <n>` before load.py", file=sys.stderr)
        return 2

    manifest = json.loads((OUT_DIR / "manifest.json").read_text())
    if manifest.get("seed") != args.seed:
        print(f"seed/out/manifest.json was generated with seed={manifest.get('seed')}, "
              f"but load.py was asked for --seed {args.seed}. Re-run generate.py first.", file=sys.stderr)
        return 2

    dataset = load_dataset()
    canonical = yaml.safe_load(CANONICAL_FIXTURE.read_text())

    identity = compute_identity(dataset["parts"], canonical["part"])
    parts_local = build_parts_local(identity["records"])

    with psycopg.connect(db_env.erp_dsn()) as erp_conn:
        erp_loader.load(erp_conn, dataset, canonical, parts_local)
    with psycopg.connect(db_env.mes_dsn()) as mes_conn:
        mes_loader.load(mes_conn, dataset, canonical, parts_local)
    with psycopg.connect(db_env.wms_dsn()) as wms_conn:
        wms_loader.load(wms_conn, dataset, canonical, parts_local)

    identity_truth_path = OUT_DIR / "identity_truth.json"
    identity_truth_path.write_text(json.dumps(identity["records"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"seed={args.seed}")
    print(f"loaded: {len(dataset['suppliers'])} suppliers, {len(dataset['parts'])} parts, "
          f"{len(dataset['purchase_orders'])} purchase_orders, {len(dataset['work_orders'])} work_orders, "
          f"{len(dataset['inventory_lots'])} raw inventory_lots (aggregated on load)")
    print(f"dropped due to id collision with canonical fixture part {canonical['part']['canonical_id']}: "
          f"{identity['dropped']}")
    print(f"identity_truth written to {identity_truth_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
