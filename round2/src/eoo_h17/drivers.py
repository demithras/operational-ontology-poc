"""Domain drivers: boot an Engine from a domain pack, rebuild it from its journal, expose the world markers.

A driver owns the Engine, the in-memory Journal (survives a simulated crash), the external-system fake, and a
mutable clock. Nothing here decides what is allowed: that is the Engine's job; the oracle never calls a driver.
"""
from __future__ import annotations

import copy
import functools
import sys

from eoo_engine import Engine, EngineError, Journal
from eoo_engine.canon import digest
from eoo_exp.util import ROOT

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domains._pack import boot, load_ir  # noqa: E402

MFG_NOW, MFG_LATER = "2026-01-01T00:00:02+00:00", "2026-01-01T00:01:00+00:00"
PRJ_NOW = "2026-10-02T12:00:00+00:00"


@functools.lru_cache(maxsize=None)
def _project_seed(state: str) -> dict:
    from domains.project.seed_from_repo import build_seed
    return build_seed(h15_state=state)


def _prop(seed: dict, typ: str, key, **changes) -> None:
    for o in seed["ops"]:
        if o["op"] == "create" and o["type"] == typ and o["key"] == key:
            o["props"].update(changes)
            for k in [k for k, v in changes.items() if v is None]:
                del o["props"][k]
            return
    raise KeyError((typ, key))


_BINDINGS: dict = {}


class Driver:
    """Subclasses set DOMAIN, PROFILES, MODES and implement ``_fresh`` (pack, package) and the world markers."""

    DOMAIN = ""
    PROFILES: tuple = ()
    MODES: tuple = ("ok",)

    def __init__(self, profile: str):
        self.profile = profile
        self.clock = {"now": self.NOW}
        self.journal = Journal()
        self.pack, self.package = self._fresh(profile)
        self.adapter = self._adapter()
        self.engine = self._boot(seed=True)
        self.store0 = self.engine.state().state_hash()

    def _boot(self, faults=(), seed=False) -> Engine:
        return boot(self.DOMAIN, self.pack, package=self.package, clock=lambda: self.clock["now"],
                    journal=self.journal, faults=faults, seed=seed)

    def rebuild(self, faults=()) -> Engine:
        """A new Engine from the same journal (a process restart). The external system and the clock survive."""
        self.engine = self._boot(faults=faults, seed=False)
        return self.engine

    # ---- world markers -------------------------------------------------------------------------
    def store_hash(self) -> str:
        return self.engine.state().state_hash()

    def effect_digest(self) -> str:
        return digest(list(self.engine.effect_log.entries()))

    def marker(self) -> dict:
        return {"store": self.store_hash(), "effect_log": len(self.engine.effect_log),
                "effect_digest": self.effect_digest(), "external": self.external_count(),
                "external_fp": self.external_fingerprint()}

    def set_mode(self, mode: str) -> None:
        self.adapter.mode = mode

    def ref_keys(self, type_id: str) -> list:
        try:
            return [r["key"] for r in self.engine.dispatch("object_types", "list", type_id)]
        except EngineError:
            return []


class MfgDriver(Driver):
    DOMAIN, NOW = "manufacturing", MFG_NOW
    PROFILES = ("std",)
    MODES = ("ok", "timeout", "commit_no_response")

    def _fresh(self, profile):
        from domains.manufacturing.pack import build_pack
        pack = build_pack()
        pack[1][("external_call", "WMS")].stock[("PX-900", "WH-C")] = 10 ** 6  # adapter side only: no drift
        return pack, None

    def _adapter(self):
        return self.pack[1][("external_call", "WMS")]

    def boot_extra(self):
        from eoo_engine import Principal
        self.engine.register_principal(Principal("stranger", frozenset({"planner"}), frozenset()))

    def external_count(self) -> int:
        return len(self.adapter.records)

    def external_fingerprint(self) -> str:
        return digest({"stock": sorted(self.adapter.stock.items()), "records": sorted(self.adapter.records)})


class PrjDriver(Driver):
    DOMAIN, NOW = "project", PRJ_NOW
    PROFILES = ("std", "nopre", "running")
    MODES = ("ok", "timeout")

    def _fresh(self, profile):
        from domains.project.adapters.git_fake import GitFake
        from domains.project.pack import build_pack
        sd = copy.deepcopy(_project_seed("RUNNING" if profile == "running" else "EVALUATED"))
        pkg = None
        if profile == "nopre":  # isolates the policy gate: start_run has no precondition in front of it
            _prop(sd, "Hypothesis", "H16", freeze_hash=None)
            pkg = copy.deepcopy(load_ir("project"))
            for a in pkg["actions"]:
                if a["id"] == "start_run":
                    a["preconditions"] = []
        git = GitFake(head=sd["head_commit"], clock=lambda: PRJ_NOW)
        if profile not in _BINDINGS:  # bindings are stateless: build once per profile (80 ms -> 0)
            _BINDINGS[profile] = build_pack(sd, git=git)[0]
        return (_BINDINGS[profile], {("git_change", "*"): git}, sd), pkg

    def _adapter(self):
        return self.pack[1][("git_change", "*")]

    def boot_extra(self):
        return None

    def external_count(self) -> int:
        return len(self.adapter.commits)

    def external_fingerprint(self) -> str:
        return digest({"head": self.adapter.head, "n": len(self.adapter.commits)})


DRIVERS = {"manufacturing": MfgDriver, "project": PrjDriver}


def new_driver(domain: str, profile: str) -> Driver:
    d = DRIVERS[domain](profile)
    d.boot_extra()
    d.store0 = d.store_hash()
    return d
