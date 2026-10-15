"""G4-E26: a Byzantine case and its honest twin run in TWO ExternalWorlds ("ext" and "ext-twin") that follow the IDENTICAL absolute clock
schedule. This helper starts such a private pair for the in-process users (mutation proof, self-test, conformance); the launcher starts
the same pair for real runs. Both worlds hold the same frozen seed."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from r3_shared.extworld import start_external

from . import specs

TWIN_DIR = "ext-twin"


class Pair:
    def __init__(self, d: Path, prefix: str = "r3w", seed: bool = True):
        from .runner import seed_external            # local: runner imports caserun, which must not import this module
        self.d = Path(d)
        self.d.mkdir(parents=True, exist_ok=True)
        sp = self.d / "systems.json"
        sp.write_text(json.dumps(specs.combined_systems()))
        self.main = start_external(self.d / "ext", sp, os.path.join(tempfile.mkdtemp(prefix=prefix), "s"))
        try:
            self.twin = start_external(self.d / TWIN_DIR, sp, os.path.join(tempfile.mkdtemp(prefix=prefix + "t"), "s"))
        except Exception:
            self.main.close()
            raise
        self.ctl, self.twin_ctl = self.main.client(), self.twin.client()
        self.sysseed = seed_external(self.ctl) if seed else None      # seed=False: runner.run_variant seeds both worlds itself
        if seed:
            seed_external(self.twin_ctl)
        self.closed = None

    def attach(self, ctx) -> None:
        ctx.attach_twin(self.twin_ctl, str(self.d / TWIN_DIR))

    def close(self) -> dict:
        if self.closed is None:                      # idempotent: each world is closed exactly once
            a = self.main.close()
            self.closed = {"external": a, "external_twin": self.twin.close()}
        return self.closed
