"""Function-call and read catalogs, derived from the IR plain JSON (never from the Engine's logic)."""
from __future__ import annotations

import json
from functools import lru_cache

from domains._pack import load_ir

INVALID_VARIANTS = ("unknown_ref", "missing_arg", "wrong_type", "extra_arg")


@lru_cache(maxsize=None)
def function_specs(domain: str) -> tuple:
    return tuple((f["id"], tuple((p["name"], p["type"], p.get("required", True)) for p in f.get("inputs", [])))
                 for f in load_ir(domain)["functions"])


def _value(drv, typ, pick: int, invalid: bool):
    if isinstance(typ, dict) and "ref" in typ:
        keys = drv.ref_keys(typ["ref"])
        return "NOPE" if invalid or not keys else keys[pick % len(keys)]
    if typ == "integer":
        return "NaN" if invalid else pick % 50
    if typ == "string":
        return pick if invalid else f"s{pick % 7}"
    return None if invalid else {"v": pick % 3}


def make_call(drv, pick: int, variant: int) -> tuple:
    """(function id, args, variant label). variant 0..1 valid arguments; 2.. one of INVALID_VARIANTS."""
    specs = function_specs(drv.DOMAIN)
    fid, params = specs[pick % len(specs)]
    label = "valid" if variant < 2 else INVALID_VARIANTS[(variant - 2) % len(INVALID_VARIANTS)]
    args = {n: _value(drv, t, pick // 7 + i, label in ("unknown_ref", "wrong_type")) for i, (n, t, _r) in enumerate(params)}
    if label == "missing_arg" and args:
        args.pop(next(iter(args)))
    if label == "extra_arg":
        args["unexpected"] = 1
    return fid, args, label


def read_targets(drv) -> list:
    return sorted(drv.engine.model.all("object_types"))


def call_key(fid, args) -> str:
    return json.dumps([fid, args], sort_keys=True, default=str)
