"""Generated, capability-aware Toolchain surface for one deployment (R3 least exposure).

The surface classes are GENERATED from the compiled IR by the vendored Toolchain (`build`) and loaded; tools a
principal's capability sets do not grant are never built. `Exposure` caches nothing across authority changes: a new
`SurfaceFactory` is made whenever the authority is replaced.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from paladin.toolchain.build import build, load_generated
from paladin.toolchain.runtime import EngineClient, UnknownTool, Who, World

_TMP = tempfile.TemporaryDirectory(prefix="paladin-gen-")


def who_of(p, delegator=None) -> Who:
    return Who(p.pid, frozenset(p.roles), frozenset(tuple(r) for r in p.relations), delegator)


class BoundClient(EngineClient):
    """Engine client whose `propose` routes through the deployment (the only commit path) with a fixed principal."""

    def __init__(self, engine, propose):
        super().__init__(engine)
        self._propose = propose

    def propose(self, aid, inputs, principal, key=None):
        return self._propose(aid, inputs, key)


class SurfaceFactory:
    def __init__(self, ir: dict):
        info = build(ir, _TMP.name)
        _sdk, _caps, self._mod = load_generated(_TMP.name, info["package"])
        self.tool_of_op = {aid: name for name, (aid, _fn) in self._mod.AgentSurface.ACTION_TOOLS.items()}
        self.tool_inventory = info["tools"]

    def surface(self, engine, who: Who, propose, object_types) -> object:
        view = engine.read_view()
        world = World({t: [r["key"] for r in view.list(t)] for t in object_types})
        world.view = view
        return self._mod.AgentSurface(BoundClient(engine, propose), who, world=world)

    def granted_operations(self, surf) -> set:
        granted = {a.split("|", 1)[0] for a in surf._caps["actionable"]}
        return {op for op, tool in self.tool_of_op.items() if tool in surf.tools and op in granted}


__all__ = ["SurfaceFactory", "UnknownTool", "who_of"]
