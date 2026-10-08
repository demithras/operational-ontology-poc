"""Low-channel read surface (PROT-H26 s3, P1e-5): read_object / list_objects / list_links / query / read. Each answer is
computed from the observer's LowView (lowview.py) - there is no second visibility code path. A bad token behaves as an
observer that can see nothing (hidden == absent), never as a distinct error."""
from __future__ import annotations

import copy
import sqlite3

from r3_shared.variant import CallResult

from .interp import HelperError
from .lowview import LowView, ViewBuilder
from .validation import RequestInvalid, validate_inputs
from .worldview import WorldView

NOT_FOUND = CallResult("INVALID", {"reason": "not_found"})


class LowReads:
    def _low_init(self) -> None:
        self._vb = ViewBuilder(self._spec)

    def _view(self, h, token: str) -> tuple[str | None, LowView, WorldView]:
        sub = self.authenticate(token)
        world = WorldView.load(h, self._spec, self._clock.now())
        return sub, self._vb.build(self._policy, sub, world, self._clock.now()), world

    def _low(self, token: str, fn):
        """Run fn(sub, lowview, world) under the service lock on a fresh handle; crashed -> UNAVAILABLE."""
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            h = self._factory("conventional-service")
            try:
                return fn(*self._view(h, token), h)
            except sqlite3.Error:
                return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})
            finally:
                h.close()

    def _mutant_split(self, world: WorldView, ref: str) -> bool:
        return self.mutant("existence_status_split") and world.props(*ref.split(":", 1)) is not None

    def read_object(self, token: str, ref: str) -> CallResult:
        def go(sub, lv, world, h):
            if not isinstance(ref, str) or ":" not in ref or not lv.has(ref):
                if isinstance(ref, str) and ":" in ref and self._mutant_split(world, ref):
                    return CallResult("DENIED", {"reason": "forbidden"})  # BUG: 403 for hidden-but-existing, 404 for absent
                return NOT_FOUND
            return CallResult("OK", {"ref": ref, "props": copy.deepcopy(lv.props[ref])})
        return self._low(token, go)

    def list_objects(self, token: str, type_: str) -> CallResult:
        def go(sub, lv, world, h):
            if type_ not in {t["name"] for t in self._spec["resource_types"]}:  # schema-level metadata is public (D3)
                return CallResult("INVALID", {"reason": "unknown_type"})
            return CallResult("OK", {"refs": sorted(r for r in lv.vis if r.startswith(type_ + ":"))})
        return self._low(token, go)

    def list_links(self, token: str, ref: str, link_type: str) -> CallResult:
        def go(sub, lv, world, h):
            if link_type not in {x["name"] for x in self._spec["link_types"]}:
                return CallResult("INVALID", {"reason": "unknown_link_type"})
            vis = isinstance(ref, str) and lv.has(ref)
            out = sorted(b for lt, a, b in lv.links if vis and lt == link_type and a == ref)
            inn = sorted(a for lt, a, b in lv.links if vis and lt == link_type and b == ref)
            return CallResult("OK", {"out": out, "in": inn})
        return self._low(token, go)

    def query(self, token: str, name: str, args: dict) -> CallResult:
        def go(sub, lv, world, h):
            defs = {r["name"]: r for r in self._spec["reads"] + self._spec["helpers"]}
            if not isinstance(name, str) or name not in defs or name not in self._helpers:
                return CallResult("INVALID", {"reason": "unknown_read"})
            low = WorldView(lv.props, {lt: sorted((a, b) for t, a, b in lv.links if t == lt) for lt in
                                       {x["name"] for x in self._spec["link_types"]}}, self._clock.now())
            sch = tuple((i["name"], i["type"], bool(i["required"])) for i in defs[name]["inputs"])
            res = {i["name"]: i["resource_type"] for i in defs[name]["inputs"] if i["type"] == "resource"}
            try:
                vals = validate_inputs(sch, args)
                ctx = self._ctx(h, vals, res, "", view=low)
                kw = {k: (res[k], v) if k in res else v for k, v in vals.items()}
                return CallResult("OK", {"value": copy.deepcopy(self._helpers[name](ctx, **kw))})
            except RequestInvalid as exc:
                return CallResult("INVALID", {"reason": exc.reason})
            except HelperError:
                return CallResult("INVALID", {"reason": "helper_error"})
        return self._low(token, go)

    def read(self, token: str, operation: str, args: dict) -> CallResult:
        """H23 read(), redefined onto the P1e-5 forms (ruling Q12)."""
        if self.authenticate(token) is None and not self.crashed:
            return CallResult("DENIED", {"reason": "invalid_token"})
        if operation in ("get", "list"):
            sch = (("type", "string", True), ("key", "string", operation == "get"))
            try:
                a = validate_inputs(sch, args)
            except RequestInvalid as exc:
                return CallResult("INVALID", {"reason": exc.reason})
            return self.read_object(token, f"{a['type']}:{a['key']}") if operation == "get" else \
                self.list_objects(token, a["type"])
        return self.query(token, operation, args)
