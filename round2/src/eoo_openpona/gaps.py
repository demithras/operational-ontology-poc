"""Constructs listed in ontology/openpona_gaps.json. render() raises Unrepresentable for any of them.

The gap list is read from the committed JSON so the code and the evidence file cannot drift apart:
every entry must carry a 'detector' this module knows; an unknown detector is an error.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .errors import Unrepresentable

GAPS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "openpona_gaps.json"
DETECTORS: dict = {}


@lru_cache(maxsize=1)
def gaps() -> list:
    data = json.loads(GAPS_PATH.read_text())
    for g in data:
        if g.get("detector") not in DETECTORS:
            raise RuntimeError(f"openpona_gaps.json entry {g.get('ir_path')!r} has no known detector")
    return data


def check_representable(ir: dict) -> None:
    for g in gaps():
        hit = DETECTORS[g["detector"]](ir)
        if hit:
            raise Unrepresentable("gap", f"{g['ir_path']}: {hit} ({g['reason']})")
