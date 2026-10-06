"""Boot helper shared by tests and scripts: build an Engine from a domain pack (the only thing it is given)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from eoo_engine import Engine, Principal

ROOT = Path(__file__).resolve().parents[1]


DEFAULT_IR = {"project": "v3"}  # the contract used by new runs (H18w); v2 = H16-H22 / exp-h18-001, "v1" (ir.json) is H15's frozen Gate-0 input


def load_ir(domain: str, version: Optional[str] = None) -> dict:
    """``version`` "v1" is the frozen ``ir.json``; any other value loads ``ir.<version>.json``; None = the default."""
    version = version or DEFAULT_IR.get(domain, "v1")
    name = "ir.json" if version == "v1" else f"ir.{version}.json"
    return json.loads((ROOT / "domains" / domain / name).read_text())


def _register(engine: Engine, plain: dict) -> None:
    db = plain.get("delegated_by")
    if db is not None and db["pid"] not in engine.directory:
        _register(engine, db)
    engine.register_principal(Principal.from_plain(plain))


def boot(domain: str, pack: tuple, *, package: Optional[dict] = None, clock: Optional[Callable[[], str]] = None,
         journal: Any = None, faults=(), seed: bool = True) -> Engine:
    """``pack`` = (LogicBindings, adapters, seed). ``package`` overrides the IR (tests only, for patched variants)."""
    bindings, adapters, seed_data = pack
    engine = Engine(package if package is not None else load_ir(domain), bindings, adapters, journal=journal,
                    clock=clock, faults=faults)
    if seed:
        for p in seed_data.get("principals", []):
            _register(engine, p)
        if seed_data.get("ops"):
            engine.seed(seed_data["ops"])
    return engine
