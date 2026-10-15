"""Immutable snapshots of Engine state handed to callers (Engine v1.1).

Every execution record (and anything nested in it: gates, inputs, approvals, responses ...) that leaves the Engine
through a public API is a ``snapshot``: a deep copy made through canonical JSON (so it shares no object with the
Engine's internal state) whose containers refuse mutation with ``CapabilityError``, the Engine's existing error for
writes to read-only objects. ``FrozenDict``/``FrozenList`` subclass dict/list so equality, ``json`` and iteration keep
working; ``dict.__setitem__(snap, ...)``-style unbound calls can still edit the DETACHED copy, which has no path back
into the Engine (interpreter-level escapes are a disclosed limit, as for every in-process discipline here).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Iterator

from .canon import to_plain
from .errors import CapabilityError


def _refuse(self, *args, **kwargs):
    raise CapabilityError("returned Engine records are read-only snapshots; use the Engine API to act")


class FrozenDict(dict):
    __slots__ = ()
    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _refuse  # type: ignore

    def __reduce__(self):
        return (FrozenDict, (dict(self),))

    def __repr__(self) -> str:
        return f"FrozenDict({dict.__repr__(self)})"


class FrozenList(list):
    __slots__ = ()
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _refuse  # type: ignore
    append = extend = insert = remove = pop = clear = sort = reverse = _refuse  # type: ignore

    def __reduce__(self):
        return (FrozenList, (list(self),))

    def __repr__(self) -> str:
        return f"FrozenList({list.__repr__(self)})"


def _seal(v: Any) -> Any:
    if isinstance(v, dict):
        return FrozenDict({k: _seal(x) for k, x in v.items()})
    if isinstance(v, list):
        return FrozenList(_seal(x) for x in v)
    return v


def snapshot(v: Any) -> Any:
    """Detached (canonical-JSON copy), deeply read-only value."""
    return _seal(to_plain(v))


class ExecutionsView(Mapping):
    """Read-only mapping execution id -> snapshot of that execution record (built on each access)."""

    __slots__ = ("_get", "_keys")

    def __init__(self, get: Callable[[str], dict], keys: Callable[[], list]):
        object.__setattr__(self, "_get", get)
        object.__setattr__(self, "_keys", keys)

    def __setattr__(self, k, v):
        _refuse(self)

    def __getitem__(self, xid: str):
        return snapshot(self._get(xid))

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

    def __repr__(self) -> str:
        return f"ExecutionsView({list(self._keys())!r})"
