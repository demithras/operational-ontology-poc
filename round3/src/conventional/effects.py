"""Resolve an operation's declarative effects against the pre-commit view, then apply them through the WorldHandle."""
from __future__ import annotations

from typing import Any

from r3_shared.world import WorldConflict

from .interp import Ctx, ev


class EffectRejected(Exception):
    """An effect conflicts with canonical state (missing target, differing existing object). Rolls the transaction back."""


def _val(node: dict, ctx: Ctx) -> Any:
    v = ev(node, ctx)
    return v[1] if isinstance(v, tuple) else v


def _ref(node: dict, ctx: Ctx, type_hint: str) -> str:
    v = ev(node, ctx)
    if isinstance(v, tuple):
        return f"{v[0]}:{v[1]}"
    if v is None:
        raise EffectRejected("link endpoint unresolved")
    return f"{type_hint}:{v}"


def resolve(effects: list[dict], ctx: Ctx) -> list[dict]:
    out = []
    for e in effects:
        k = e["kind"]
        if k in ("create", "update", "delete"):
            key = _val(e["key"], ctx)
            if key is None:
                raise EffectRejected(f"{k} {e['type']}: key unresolved")
            props = {n: _val(x, ctx) for n, x in e.get("props", {}).items()}
            out.append({"kind": k, "type": e["type"], "key": str(key),
                        "props": {n: v for n, v in props.items() if v is not None}})
        elif k in ("link", "unlink"):
            lt = ctx.link_types[e["link_type"]]
            out.append({"kind": k, "link_type": e["link_type"], "src": _ref(e["src"], ctx, lt["from_types"][0]),
                        "dst": _ref(e["dst"], ctx, lt["to_types"][0])})
        elif k == "external":
            out.append({"kind": k, "adapter": e["adapter"], "target": e["target"],
                        "payload": {n: _val(x, ctx) for n, x in e["payload"].items()}})
        else:
            raise EffectRejected(f"unsupported effect kind {k}")
    return out


def apply(handle, effects: list[dict], request_id: str | None, unavailable: set[str]) -> int:
    n = 0
    for e in effects:
        k = e["kind"]
        try:
            if k == "create":
                cur = handle.get(e["type"], e["key"])
                if cur is None:
                    handle.create(e["type"], e["key"], e["props"])
                    n += 1
                elif any(cur["props"].get(p) != v for p, v in e["props"].items()):
                    raise EffectRejected(f"{e['type']}:{e['key']} exists with different content")
            elif k == "update":
                if e["props"]:
                    handle.update(e["type"], e["key"], e["props"])
                    n += 1
            elif k == "delete":
                handle.delete(e["type"], e["key"])
                n += 1
            elif k in ("link", "unlink"):
                for end in (e["src"], e["dst"]):
                    t, key = end.split(":", 1)
                    if handle.get(t, key) is None:
                        raise EffectRejected(f"link endpoint {end} does not exist")
                (handle.link if k == "link" else handle.unlink)(e["link_type"], e["src"], e["dst"])
                n += 1
            else:
                if e["adapter"] in unavailable:
                    raise ConnectionError(f"adapter {e['adapter']} unavailable")
                handle.external_write(e["adapter"], e["target"], e["payload"], request_id)
                n += 1
        except WorldConflict as exc:
            raise EffectRejected(str(exc)) from exc
    return n
