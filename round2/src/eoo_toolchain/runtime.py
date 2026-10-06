"""Generic runtime used by generated surfaces: SDK base classes, client adapter, world model, agent-surface base.

Nothing here knows a domain. A *client* is any object with get/list/follow/follow_one/interface_query/call_function/propose
(``EngineClient`` adapts an Engine by duck typing; this module does not import the Engine).
"""
from __future__ import annotations

import dataclasses
import itertools
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Union

from .capdecide import decide

Key = Union[str, int]


class UnknownTool(KeyError):
    """The requested tool does not exist on this surface (absent, not refused)."""


@dataclass(frozen=True)
class Who:
    pid: str
    roles: frozenset = frozenset()
    relations: frozenset = frozenset()
    delegated_by: Optional["Who"] = None

    @classmethod
    def from_plain(cls, d: dict) -> "Who":
        db = d.get("delegated_by")
        return cls(d["pid"], frozenset(d.get("roles", ())), frozenset(tuple(r) for r in d.get("relations", ())),
                   None if db is None else cls.from_plain(db))


@dataclass(frozen=True)
class Obj:
    """Base of generated object types."""
    TYPE: ClassVar[str] = ""


@dataclass(frozen=True)
class _Call:
    ID: ClassVar[str] = ""

    def args(self) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self) if getattr(self, f.name) is not None}


@dataclass(frozen=True)
class FunctionCall(_Call):
    """Read-only computation: ``call(client)``; never proposes anything."""
    KIND: ClassVar[str] = "function"

    def call(self, client, principal=None):
        return client.call_function(self.ID, self.args(), principal)


@dataclass(frozen=True)
class ActionRequest(_Call):
    """Governed state change request: ``propose(client, principal)``; the Engine decides and journals."""
    KIND: ClassVar[str] = "action"
    CAPABILITY: ClassVar[str] = ""

    def propose(self, client, principal, idempotency_key=None):
        return client.propose(self.ID, self.args(), principal, idempotency_key)


def materialize(cls, rec):
    if rec is None:
        return None
    props = dict(rec.get("props", {}))
    pk = getattr(cls, "PK", None)
    if pk is not None and pk not in props and "key" in rec:
        props[pk] = rec["key"]
    names = [f.name for f in dataclasses.fields(cls)]
    return cls(**{n: props.get(n) for n in names})


def get_object(client, cls, key):
    return materialize(cls, client.get(cls.TYPE, key))


def list_objects(client, cls):
    return [materialize(cls, r) for r in client.list(cls.TYPE)]


def interface_list(client, iface: str, classes: dict):
    """One generic tool for any interface: no implementer is named anywhere in generated code."""
    return [materialize(classes[r["type"]], r) for r in client.interface_query(iface)]


def follow_links(client, link: str, cls_from, key, direction, target_cls_by_type, single: bool):
    t = cls_from.TYPE
    if single:
        r = client.follow_one(link, t, key, direction)
        return None if r is None else materialize(target_cls_by_type[r["type"]], r)
    return [materialize(target_cls_by_type[r["type"]], r) for r in client.follow(link, t, key, direction)]


class EngineClient:
    """Adapts an Engine (duck-typed) to the client interface above."""

    def __init__(self, engine):
        self._e = engine

    def get(self, t, key):
        return self._e.get(t, key)

    def list(self, t):
        return self._e.read_view().list(t)

    def follow(self, lt, t, key, direction="out"):
        return self._e.read_view().follow(lt, t, key, direction)

    def follow_one(self, lt, t, key, direction="out"):
        return self._e.read_view().follow_one(lt, t, key, direction)

    def interface_query(self, iface):
        return self._e.interface_query(iface)

    def call_function(self, fid, args, principal=None):
        return self._e.call_function(fid, args, principal)

    def propose(self, aid, inputs, principal, key=None):
        return self._e.propose(aid, inputs, principal, idempotency_key=key)

    def principal_plain(self, pid):
        return self._e.principal_of(pid).to_plain() if pid in self._e.directory else None

    def world(self, object_types):
        view = self._e.read_view()
        w = World({t: [r["key"] for r in view.list(t)] for t in object_types})
        w.view = view
        return w


@dataclass
class World:
    """The object set a principal's surface is derived over: type -> keys, plus harness-supplied flags."""
    objects: dict
    flags: dict = field(default_factory=dict)
    view: Any = None


def bkey(binding: dict) -> str:
    return json.dumps({k: v for k, v in binding.items() if v is not None}, sort_keys=True, separators=(",", ":"))


def _candidates(tables: dict, declared: str, world: World) -> list:
    if declared in world.objects:
        return [(k, declared) for k in world.objects[declared]]
    return [(k, t) for t in sorted(tables["implementers"].get(declared, ())) for k in world.objects.get(t, ())]


def bindings_of(tables: dict, act: dict, world: World):
    """Every request binding of an action's ref inputs over the world: yields (binding dict, resources tuple)."""
    slots = []
    for ref in act["slots"]:
        cands = _candidates(tables, ref["declared"], world)
        opts = [(None, None)] if (not ref["required"]) else []
        opts += [(c, c) for c in cands]
        slots.append((ref, opts))
    for combo in itertools.product(*[o for _r, o in slots]) if slots else [()]:
        b, res = {}, []
        for (ref, _o), (val, cand) in zip(slots, combo):
            if cand is None:
                b[ref["name"]] = None
                continue
            key, actual = cand
            b[ref["name"]] = [key] if ref["list"] else key
            res.append((ref["declared"], key, actual))
        res += [(t, None, t) for t in act["effect_targets"]]
        yield b, tuple(res)


class AgentSurfaceBase:
    """Per-principal tool surface. Tools the principal's capability sets do not grant are never built: ``call`` raises
    UnknownTool for them and there is no attribute for them. Subclasses (generated) fill TABLES / QUERY_TOOLS / ACTION_TOOLS."""
    TABLES: ClassVar[dict] = {}
    QUERY_TOOLS: ClassVar[dict] = {}     # name -> (capability string, fn(client, **kw))
    FUNCTION_TOOLS: ClassVar[dict] = {}  # name -> (capability string, fn(client, pid, **kw))
    ACTION_TOOLS: ClassVar[dict] = {}    # name -> (action id, fn(client, pid, idempotency_key=None, **kw))

    def __init__(self, client, principal, world: World = None, opaque: dict = None, registered: bool = True):
        self._client = client
        self.who = principal if isinstance(principal, Who) else Who.from_plain(principal)
        self.registered = registered
        self.world = world
        self.opaque = opaque or {}
        self._caps = self._derive()
        self.tools = self._build_tools()

    # -- capability derivation (generated tables + generic decision) --
    def _derive(self) -> dict:
        T = self.TABLES
        if not self.registered:
            return {"queryable": [], "actionable": [], "approvable": []}
        actionable, approvable = [], []
        for aid, act in sorted(T["actions"].items()):
            for b, res in bindings_of(T, act, self.world):
                if decide(T, act["authority"], self.who, "action:" + aid, res, self.opaque, self.world):
                    actionable.append(f"{aid}|{bkey(b)}")
                for cap in act["approval_caps"]:
                    if decide(T, act["authority"], self.who, cap, res, self.opaque, self.world):
                        approvable.append(f"{aid}|{cap}|{bkey(b)}")
        queryable = sorted(cap for cap, _f in self.QUERY_TOOLS.values()) + sorted(cap for cap, _f in self.FUNCTION_TOOLS.values())
        return {"queryable": sorted(queryable), "actionable": sorted(set(actionable)), "approvable": sorted(set(approvable))}

    def _build_tools(self) -> dict:
        tools = {}
        if not self.registered:
            return tools
        for name, (_cap, fn) in self.QUERY_TOOLS.items():
            tools[name] = (lambda fn=fn: lambda **kw: fn(self._client, **kw))()
        for name, (_cap, fn) in self.FUNCTION_TOOLS.items():
            tools[name] = (lambda fn=fn: lambda **kw: fn(self._client, self.who.pid, **kw))()
        granted = {a.split("|", 1)[0] for a in self._caps["actionable"]}
        for name, (aid, fn) in self.ACTION_TOOLS.items():
            if aid in granted:
                tools[name] = (lambda fn=fn: lambda idempotency_key=None, **kw: fn(self._client, self.who.pid, idempotency_key, **kw))()
        return tools

    def call(self, name: str, **kw):
        fn = self.tools.get(name) if isinstance(name, str) else None
        if fn is None:
            raise UnknownTool(name)
        return fn(**kw)

    def capabilities(self) -> dict:
        visible = sorted({c.split(":", 1)[1] for c in self._caps["queryable"] if c.split(":", 1)[0] != "call"})
        return {"visible": visible, "queryable": list(self._caps["queryable"]), "actionable": list(self._caps["actionable"]),
                "approvable": list(self._caps["approvable"]), "tools": sorted(self.tools)}
