"""Consistent renaming bijection for the domain-branch audit (A5a): principal ids, body ids, matter ids, model id, case
ids, emergency ids and role names. Operation/type names, the domain name and relation names are NOT renamed (ops-spec
business rules legitimately key on them). New names are opaque (never ending in '-1', no shared prefix)."""
from __future__ import annotations

import copy
import random


def _collect(calls) -> set[str]:
    out = set()
    for c in calls:
        a = c.get("action")
        if isinstance(a, dict):
            for k in ("case", "emergency"):
                if isinstance(a.get(k), str):
                    out.add(a[k])
            args = a.get("args")
            if isinstance(args, dict) and isinstance(args.get("emergency"), str):
                out.add(args["emergency"])
    return out


class Renamer:
    def __init__(self, auth: dict, doc: dict, calls, rng: random.Random, keep_roles=()):
        ids = {p["id"] for p in auth["principals"]} | {b["id"] for b in doc["bodies"]} | {m["id"] for m in doc["matters"]}
        ids |= {doc["model"]} | _collect(calls)
        roles = {r for p in auth["principals"] for r in p["roles"]} - set(keep_roles)
        fresh = lambda: "".join(rng.choice("bcdfghjkmnpqrstvwxz") for _ in range(9))  # noqa: E731
        self.ids = {k: f"{fresh()}{rng.randrange(10 ** 6)}" for k in sorted(ids)}
        self.roles = {k: f"{fresh()}" for k in sorted(roles)}
        self.back = {v: k for k, v in self.ids.items()}

    def _walk(self, o, m, key=None):
        if isinstance(o, str):
            return m.get(o, o)
        if isinstance(o, list):
            return [self._walk(x, m, key) for x in o]
        if isinstance(o, dict):
            return {k: self._walk(v, m, k) for k, v in o.items()}
        return o

    def fwd(self, o):
        return self._walk(copy.deepcopy(o), self.ids)

    def inv(self, o):
        return self._walk(copy.deepcopy(o), self.back)

    def auth(self, spec: dict) -> dict:
        s = self._role_walk(copy.deepcopy(spec))
        return self.fwd(s)

    def _role_walk(self, o, key=None):
        if isinstance(o, str):
            return self.roles.get(o, o) if key in ("role", "roles") else o
        if isinstance(o, list):
            return [self._role_walk(x, key) for x in o]
        if isinstance(o, dict):
            return {k: self._role_walk(v, k) for k, v in o.items()}
        return o

    def call(self, c: dict) -> dict:
        """Transform one recorded call into its renamed twin."""
        c = copy.deepcopy(c)
        for k in ("actor", "obo", "action", "doc"):
            if c.get(k) is not None:
                c[k] = self.fwd(c[k])
        if c.get("spec") is not None:
            c["spec"] = self.auth(c["spec"])
        if c.get("rid") is not None:
            c["rid"] = self.ids.get(c["rid"], c["rid"])
        return c

    def canon_out(self, o):
        """Inverse-rename an outcome/mark structure and sort order-sensitive id lists (`bodies`)."""
        o = self.inv(o)
        return _sort_bodies(o)


def _sort_bodies(o):
    if isinstance(o, dict):
        return {k: (sorted(v) if k == "bodies" and isinstance(v, list) else _sort_bodies(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_sort_bodies(x) for x in o]
    return o
