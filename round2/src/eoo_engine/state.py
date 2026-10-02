"""Canonical object/link state (one immutable-by-convention snapshot) and its read operations."""
from __future__ import annotations

from typing import Any, Optional

from .canon import digest, to_plain


class State:
    """objects: (type, key) -> {"props": dict, "ver": int}; links: (link type, (t, k), (t, k)) -> {...}."""

    def __init__(self, model, objects: Optional[dict] = None, links: Optional[dict] = None):
        self.model = model
        self.objects: dict = objects if objects is not None else {}
        self.links: dict = links if links is not None else {}

    def fork(self) -> "State":
        return State(self.model, dict(self.objects), dict(self.links))

    # ---- reads -------------------------------------------------------------------------
    def get(self, t: str, key: Any) -> Optional[dict]:
        rec = self.objects.get((t, key))
        return None if rec is None else {"props": to_plain(rec["props"]), "ver": rec["ver"]}

    def version(self, t: str, key: Any) -> Optional[int]:
        rec = self.objects.get((t, key))
        return None if rec is None else rec["ver"]

    def keys(self, t: str) -> list:
        return sorted((k for (tt, k) in self.objects if tt == t), key=repr)

    def locate(self, declared: str, key: Any) -> list[tuple[str, Any]]:
        """Concrete (type, key) pairs a reference ``key`` to ``declared`` (type or interface) denotes."""
        if declared in self.model.all("object_types"):
            return [(declared, key)] if (declared, key) in self.objects else []
        return [(t, key) for t in sorted(self.model.implementers.get(declared, ())) if (t, key) in self.objects]

    def resolve_problem(self, declared: str, key: Any) -> Optional[str]:
        if self.model.is_import(declared):
            return None  # imported type: outside this package, key accepted unchecked
        hits = self.locate(declared, key)
        if len(hits) == 1:
            return None
        return f"no {declared} with key {key!r}" if not hits else f"key {key!r} is ambiguous for {declared}"

    def links_of(self, lt: str, end: tuple, outgoing: bool) -> list[tuple]:
        """Link records of type ``lt`` leaving (outgoing) or entering ``end`` = (type, key)."""
        idx = 1 if outgoing else 2
        return sorted((k for k in self.links if k[0] == lt and k[idx] == end), key=repr)

    def snapshot(self) -> dict:
        objs = [[t, k, to_plain(r["props"]), r["ver"]] for (t, k), r in self.objects.items()]
        lnks = [[lt, list(s), list(d), to_plain(r["props"]), r["ver"]] for (lt, s, d), r in self.links.items()]
        return {"objects": sorted(objs, key=repr), "links": sorted(lnks, key=repr)}

    def state_hash(self) -> str:
        return digest(self.snapshot())
