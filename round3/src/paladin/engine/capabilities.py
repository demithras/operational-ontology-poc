"""Unforgeable capabilities.

* ``WriteGrant``: the only thing the store / effect dispatcher accepts for a write. It cannot be
  constructed directly; only ``Minter.mint`` (held by the Engine's action pipeline) creates one, bound
  to one execution id, and the store accepts it only while the minter lists that very object as live.
* Logic and tools never receive the store, the minter or adapters: they get read-only objects whose
  attributes are plain closures (``ReadOnly``), so no attribute path leads to a write method.
Python is not a security sandbox: interpreter introspection (``__closure__``/``__globals__``/``gc``)
can escape any in-process discipline; the guarantee here is "no attribute path and no API".
"""
from __future__ import annotations

import secrets
from typing import Any, Callable

from .errors import CapabilityError


class WriteGrant:
    __slots__ = ("execution", "token", "__weakref__")

    def __init__(self, *args, **kwargs):
        raise CapabilityError("WriteGrant can only be minted by the action pipeline")

    def __setattr__(self, k, v):
        raise CapabilityError("WriteGrant is immutable")

    def __repr__(self) -> str:
        return f"<WriteGrant execution={self.execution!r}>"


class Minter:
    def __init__(self):
        self._live: dict[str, WriteGrant] = {}

    def mint(self, execution: str) -> WriteGrant:
        g = object.__new__(WriteGrant)
        object.__setattr__(g, "execution", execution)
        object.__setattr__(g, "token", secrets.token_hex(16))
        self._live[g.token] = g
        return g

    def revoke(self, grant: WriteGrant) -> None:
        self._live.pop(getattr(grant, "token", None), None)

    def verifier(self) -> Callable[[Any, str], None]:
        live = self._live

        def verify(grant: Any, execution: str) -> None:
            if not isinstance(grant, WriteGrant):
                raise CapabilityError("write rejected: no WriteGrant")
            if live.get(getattr(grant, "token", None)) is not grant:
                raise CapabilityError("write rejected: grant is forged, revoked or not live")
            if grant.execution != execution:
                raise CapabilityError(f"write rejected: grant bound to {grant.execution!r}, not {execution!r}")
        return verify


class ReadOnly:
    """Immutable attribute bag. Values must themselves be read-only (frozen data or closures)."""

    __slots__ = ("_fields",)

    def __init__(self, **fields):
        object.__setattr__(self, "_fields", _FrozenMap(fields))

    def __getattr__(self, k):
        try:
            return object.__getattribute__(self, "_fields")[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        raise CapabilityError("read-only object")

    def __delattr__(self, k):
        raise CapabilityError("read-only object")

    def __dir__(self):
        return list(object.__getattribute__(self, "_fields").keys())

    def __repr__(self) -> str:
        return f"ReadOnly({', '.join(dir(self))})"


class _FrozenMap(dict):
    """dict that refuses mutation (keeps ReadOnly attributes fixed)."""

    def _ro(self, *a, **k):
        raise CapabilityError("read-only object")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _ro  # type: ignore[assignment]


TOOL_REQUESTS = ("call_function", "propose_action")


def tool_facade(engine, principal_id: str) -> ReadOnly:
    """What an agent/tool gets: function calls and action proposals only, never a raw write."""

    def request(kind: str, *args, **kwargs):
        if kind == "call_function":
            return engine.call_function(args[0], kwargs.get("args", args[1] if len(args) > 1 else {}),
                                        principal=principal_id)
        if kind == "propose_action":
            return engine.propose(args[0], kwargs.get("inputs", args[1] if len(args) > 1 else {}), principal_id,
                                  idempotency_key=kwargs.get("idempotency_key"))
        raise CapabilityError(f"tools may request only {TOOL_REQUESTS}, not {kind!r}")

    return ReadOnly(
        request=request,
        call_function=lambda fid, args=None: request("call_function", fid, args or {}),
        propose_action=lambda aid, inputs=None, idempotency_key=None: request(
            "propose_action", aid, inputs or {}, idempotency_key=idempotency_key),
        view=engine.read_view(),
    )
