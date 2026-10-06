"""Read-only in-memory view over a world snapshot, used by the oracle's helpers and expression evaluator.

A Ref is a (type, key) tuple. Object canonical id is "Type:key".
"""
from __future__ import annotations

from typing import Any

Ref = tuple[str, str]


class HelperError(Exception):
    """A prose-defined helper failed (e.g. head_commit with no Commit): the operation fails closed."""


def rid(ref: Ref) -> str:
    return f"{ref[0]}:{ref[1]}"


def split(canon: str) -> Ref:
    t, k = canon.split(":", 1)
    return (t, k)


class View:
    def __init__(self, snapshot: dict, now: int = 0, relations=(), config: dict | None = None):
        self.objects: dict[str, dict] = {k: dict(v["props"]) for k, v in snapshot["objects"].items()}
        self.links: set[tuple[str, str, str]] = {tuple(x) for x in snapshot["links"]}
        self.now = now
        self.relations = {tuple(r) for r in relations}
        self.config = config or {}

    # -- object access ---------------------------------------------------------------------------
    def get(self, ref: Ref | None) -> dict | None:
        return None if ref is None else self.objects.get(rid(ref))

    def exists(self, ref: Ref | None) -> bool:
        return ref is not None and rid(ref) in self.objects

    def field(self, ref: Ref | None, name: str) -> Any:
        o = self.get(ref)
        return None if o is None else o.get(name)

    def keys_of(self, type_: str) -> list[str]:
        return sorted(k.split(":", 1)[1] for k in self.objects if k.startswith(type_ + ":"))

    def refs_of(self, type_: str) -> list[Ref]:
        return [(type_, k) for k in self.keys_of(type_)]

    # -- links -------------------------------------------------------------------------------------
    def out(self, link: str, src: Ref | None) -> list[Ref]:
        if src is None:
            return []
        return [split(d) for (lt, s, d) in sorted(self.links) if lt == link and s == rid(src)]

    def inc(self, link: str, dst: Ref | None) -> list[Ref]:
        if dst is None:
            return []
        return [split(s) for (lt, s, d) in sorted(self.links) if lt == link and d == rid(dst)]

    def has_link(self, link: str, src: Ref | None, dst: Ref | None) -> bool:
        if src is None or dst is None:
            return False
        return (link, rid(src), rid(dst)) in self.links

    def linked_to(self, link: str, type_: str, dst: Ref | None) -> list[Ref]:
        return [r for r in self.inc(link, dst) if r[0] == type_]
