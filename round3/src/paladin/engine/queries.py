"""Generic reads over a State and the read-only view handed to Functions, logic and tools.

The view is a ``ReadOnly`` bag of closures: it has no write method and no attribute leads to the
store, the minter or an adapter. Every value it returns is a frozen copy.
"""
from __future__ import annotations

from typing import Any, Callable

from .canon import freeze
from .capabilities import ReadOnly
from .errors import InvalidRequest


def _record(state, t: str, key: Any):
    rec = state.get(t, key)
    return None if rec is None else freeze({"type": t, "key": key, "props": rec["props"], "ver": rec["ver"]})


def get(state, t: str, key: Any):
    """Object by type (or interface) and key; None when absent; error when ambiguous."""
    hits = state.locate(t, key)
    if len(hits) > 1:
        raise InvalidRequest(f"key {key!r} is ambiguous for {t}")
    return _record(state, *hits[0]) if hits else None


def list_objects(state, t: str) -> tuple:
    """All objects of an object type, or of every type implementing an interface."""
    m = state.model
    if t in m.all("object_types"):
        types = [t]
    elif t in m.all("interfaces"):
        types = sorted(m.implementers.get(t, ()))
    else:
        raise InvalidRequest(f"{t!r} is not an object type or interface")
    return tuple(_record(state, tt, k) for tt in types for k in state.keys(tt))


def follow(state, lt: str, t: str, key: Any, direction: str = "out") -> tuple:
    """Objects at the other end of ``lt`` links from (out) or into (in) object (t, key)."""
    spec = state.model.get("link_types", lt)
    if spec is None or direction not in ("out", "in"):
        raise InvalidRequest(f"unknown link type {lt!r} or direction {direction!r}")
    hits = state.locate(t, key)
    if len(hits) != 1:
        return ()
    outgoing = direction == "out"
    ends = [k[2] if outgoing else k[1] for k in state.links_of(lt, hits[0], outgoing)]
    return tuple(_record(state, et, ek) or freeze({"type": et, "key": ek}) for et, ek in ends)


def follow_one(state, lt: str, t: str, key: Any, direction: str = "out"):
    """Single-valued navigation; only legal where the IR cardinality of that end has max 1."""
    spec = state.model.get("link_types", lt)
    mx = None if spec is None else (spec.src_max if direction == "out" else spec.dst_max)
    if mx != 1:
        raise InvalidRequest(f"{lt} {direction}: cardinality max is {mx!r}, not 1")
    res = follow(state, lt, t, key, direction)
    return res[0] if res else None


def links(state, lt: str) -> tuple:
    return tuple(freeze({"type": k[0], "src": list(k[1]), "dst": list(k[2]), "props": r["props"]})
                 for k, r in sorted(state.links.items(), key=lambda kv: repr(kv[0])) if k[0] == lt)


def cardinality_report(state) -> tuple:
    """Min/max cardinality violations of the current state (min is reported, not enforced at commit)."""
    out = []
    for lt, spec in sorted(state.model.all("link_types").items()):
        for ot_kind, end_type, mn, mx, outgoing in ((0, spec.src, spec.src_min, spec.src_max, True),
                                                    (1, spec.dst, spec.dst_min, spec.dst_max, False)):
            for t in ([end_type] if end_type in state.model.all("object_types")
                      else sorted(state.model.implementers.get(end_type, ()))):
                for k in state.keys(t):
                    n = len(state.links_of(lt, (t, k), outgoing))
                    if n < mn or (mx != "*" and n > mx):
                        out.append(freeze({"link_type": lt, "end": "from" if outgoing else "to",
                                           "object": [t, k], "count": n, "min": mn, "max": mx}))
    return tuple(out)


def make_read_view(state_of: Callable[[], Any], call_function: Callable | None = None) -> ReadOnly:
    """Read-only view over the State returned by ``state_of()`` (current or would-be)."""
    fields = dict(
        get=lambda t, key: get(state_of(), t, key),
        list=lambda t: list_objects(state_of(), t),
        follow=lambda lt, t, key, direction="out": follow(state_of(), lt, t, key, direction),
        follow_one=lambda lt, t, key, direction="out": follow_one(state_of(), lt, t, key, direction),
        links=lambda lt: links(state_of(), lt),
        implementers=lambda iface: tuple(sorted(state_of().model.implementers.get(iface, ()))),
        interface_query=lambda iface: list_objects(state_of(), iface),
        cardinality_report=lambda: cardinality_report(state_of()),
        state_hash=lambda: state_of().state_hash(),
    )
    if call_function is not None:
        fields["call"] = call_function
    return ReadOnly(**fields)
