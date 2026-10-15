"""Picklable variant factories. The parallel mutation proof starts its workers with the 'spawn' start method (each worker imports every
module fresh and shares no process state with siblings or parent), so the factory crosses the process boundary by pickle: a name, not a
closure."""
from __future__ import annotations

import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]


class NamedFactory:
    """factory(mutants_tuple) -> a fresh Variant. `fake-*` names load a test fake (needs round3/ on sys.path); others use the registry."""

    def __init__(self, name: str):
        self.name = name

    def __call__(self, mutants=()):
        if self.name.startswith("fake-"):
            if str(ROUND3) not in sys.path:
                sys.path.insert(0, str(ROUND3))
            from tests.fakes import fake_h28
            return fake_h28.load(self.name, mutants)
        from r3_shared.registry import load_variant
        return load_variant(self.name, mutants)
