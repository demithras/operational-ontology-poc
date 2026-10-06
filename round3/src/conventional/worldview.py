"""Read-only snapshot of the canonical world, loaded INSIDE the commit transaction (R6: commit-time truth)."""
from __future__ import annotations

from typing import Any, Iterator


class WorldView:
    def __init__(self, objects: dict[str, dict], links: dict[str, list[tuple[str, str]]], now: int):
        self._objects, self._links, self.now = objects, links, now

    @classmethod
    def load(cls, handle, ops_spec: dict, now: int) -> "WorldView":
        objs: dict[str, dict] = {}
        for rt in ops_spec["resource_types"]:
            for row in handle.list(rt["name"]):
                objs[f"{rt['name']}:{row['key']}"] = row["props"]
        links = {lt["name"]: handle.links(lt["name"]) for lt in ops_spec["link_types"]}
        return cls(objs, links, now)

    # -- objects -------------------------------------------------------------------------------
    def props(self, type_: str, key: str) -> dict | None:
        return self._objects.get(f"{type_}:{key}")

    def field(self, type_: str, key: str, name: str) -> Any:
        p = self.props(type_, key)
        return None if p is None else p.get(name)

    def keys(self, type_: str) -> list[str]:
        pre = type_ + ":"
        return sorted(k[len(pre):] for k in self._objects if k.startswith(pre))

    def items(self, type_: str) -> Iterator[tuple[str, dict]]:
        for k in self.keys(type_):
            yield k, self._objects[f"{type_}:{k}"]

    # -- links ---------------------------------------------------------------------------------
    def targets(self, link: str, type_: str, key: str) -> list[str]:
        """Destination refs ('Type:key') of `link` from src `type_:key`, sorted."""
        src = f"{type_}:{key}"
        return sorted(d for s, d in self._links.get(link, ()) if s == src)

    def sources(self, link: str, type_: str, key: str) -> list[str]:
        dst = f"{type_}:{key}"
        return sorted(s for s, d in self._links.get(link, ()) if d == dst)

    def has_link(self, link: str, src: str, dst: str) -> bool:
        return (src, dst) in set(self._links.get(link, ()))

    def all_links(self, link: str) -> list[tuple[str, str]]:
        return sorted(self._links.get(link, ()))


def key_of(ref: str) -> str:
    return ref.split(":", 1)[1]


def type_of(ref: str) -> str:
    return ref.split(":", 1)[0]
