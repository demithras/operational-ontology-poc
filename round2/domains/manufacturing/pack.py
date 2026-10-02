"""The only thing the Engine is given for Manufacturing: (LogicBindings, adapters, seed)."""
from __future__ import annotations

import json
from pathlib import Path

from .adapters.erp_mes_fake import ErpFake, MesFake
from .adapters.wms_fake import WmsFake
from .logic import build_bindings

SEED_PATH = Path(__file__).with_name("seed.json")


def load_seed() -> dict:
    return json.loads(SEED_PATH.read_text())


def build_pack(seed: dict | None = None):
    seed = seed if seed is not None else load_seed()
    adapters = {("external_call", "WMS"): WmsFake.from_seed(seed), ("external_call", "ERP"): ErpFake(),
                ("external_call", "MES"): MesFake()}
    return build_bindings(), adapters, seed
