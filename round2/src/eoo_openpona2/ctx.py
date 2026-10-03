"""Compilation context: facts lookup (exactly-once rule), references, types, properties, parameters."""
from __future__ import annotations

import re

from .document import Document, Hole
from .errors import Ambiguous, Invalid, Unresolved

ENDPOINT = ("object_types", "interfaces")
EFFECT_KINDS = {"create": ("object_types",), "update": ("object_types",), "delete": ("object_types",),
                "link": ("link_types",), "unlink": ("link_types",), "git_change": ("object_types", "link_types")}
_NAT = re.compile(r"0|[1-9][0-9]*")


class _Absent:
    def __repr__(self):
        return "<absent>"


_ABSENT = _Absent()


class _C:
    def __init__(self, doc: Document):
        self.d = doc
        self.checks: list[tuple] = []  # (path, string, kinds, prefix, allow_prop, expected)
        self.used: set[tuple] = set()
        self.import_set = {s for _, s in doc.imports}

    # ------------------------------------------------------------ facts
    def raw(self, key: tuple, f: str) -> list:
        self.used.add((key, f))
        return self.d.facts.get((key, f), [])

    def all(self, key: tuple, f: str) -> list:
        return [v for _, v in self.raw(key, f)]

    def one(self, key: tuple, f: str, required: bool = True):
        got = self.raw(key, f)
        if len(got) > 1:
            raise Ambiguous(f"conflict:{f}", f"{key[1:]} states {f} {len(got)} times", got[1][0])
        if not got:
            if required:
                raise Invalid(f"missing:{f}", f"{key[1:]} never states {f}", self.d.decls.get(key))
            return _ABSENT
        return got[0][1]

    def children(self, parent: tuple, what: str) -> list[tuple]:
        return list(self.d.order.get((what, parent), []))

    # ------------------------------------------------------------ references
    def ref(self, rv: tuple, kinds, prefix: str = "", allow_prop: bool = False, path: str = "") -> str:
        """A reference value -> IR string; the bound target must be declared (or be a declared import)."""
        if rv[0] == "ext":
            _, imp, nm = rv
            if imp not in self.import_set:
                raise Unresolved("unresolved_binding", f"{path}: package {imp!r} is not imported")
            s, expected = f"{imp}#{nm}", ("import", imp)
        elif rv[0] == "prop":
            _, kind, owner, nm = rv
            if not allow_prop or kind not in kinds:
                raise Invalid("reference_role", f"{path}: a property cannot fill this slot")
            if ("prop", kind, owner, nm) not in self.d.decls:
                raise Unresolved("unresolved_binding", f"{path}: {kind} {owner!r} declares no property {nm!r}")
            s, expected = f"{owner}.{nm}", (kind, owner, nm)
        else:
            _, kind, rid = rv
            if kind not in kinds:
                raise Invalid("reference_role", f"{path}: a {kind} reference cannot fill a slot of {kinds}")
            if ("res", kind, rid) not in self.d.decls:
                raise Unresolved("unresolved_binding", f"{path}: no {kind} {rid!r} is declared")
            s, expected = prefix + rid, (kind, rid)
        self.checks.append((path, s, kinds, prefix, allow_prop, expected))
        return s

    def own_prop(self, owner: tuple, nm: str, path: str) -> str:
        if ("prop", owner[1], owner[2], nm) not in self.d.decls:
            raise Unresolved("unresolved_binding", f"{path}: {owner[1]} {owner[2]!r} declares no property {nm!r}")
        return nm

    def type_(self, tv, path: str):
        kind = tv[0]
        if kind == "prim":
            return tv[1]
        if kind == "ref":
            return {"ref": self.ref(tv[1], ENDPOINT, path=path)}
        h: Hole = tv[1]
        ctor, inner = h.value
        return {ctor: self.type_(inner, f"{path}.{ctor}")}

    # ------------------------------------------------------------ pieces
    def prop(self, key: tuple, path: str) -> dict:
        p = {"name": key[3], "type": self.type_(self.one(key, "type"), path + ".type"),
             "required": self.one(key, "required")}
        for f in ("immutable", "description"):
            v = self.one(key, f, required=False)
            if v is not _ABSENT:
                p[f] = v
        cs, empty = self.all(key, "constraints"), self.all(key, "constraints_empty")
        if cs and empty or len(empty) > 1:
            raise Ambiguous("conflict:constraints", f"{key[1:]} states both empty and listed constraints")
        if empty:
            p["constraints"] = []
        elif cs:
            p["constraints"] = cs
        return p

    def props(self, owner: tuple, path: str) -> list[dict]:
        return [self.prop(k, f"{path}[{i}]") for i, k in enumerate(self.children(owner, "props"))]

    def params(self, owner: tuple, path: str) -> list[dict]:
        out = []
        for i, k in enumerate(self.children(owner, "params")):
            p = {"name": k[3], "type": self.type_(self.one(k, "type"), f"{path}[{i}].type")}
            r = self.one(k, "required", required=False)
            if r is not _ABSENT:
                p["required"] = r
            out.append(p)
        return out

    def card(self, key: tuple, side: str) -> dict:
        mn = self.one(key, side + "_min")
        mx, star = self.all(key, side + "_max"), self.all(key, side + "_star")
        if len(mx) + len(star) > 1:
            raise Ambiguous(f"conflict:{side}_max", f"{key[1:]} states its {side} upper bound more than once")
        if not mx and not star:
            raise Invalid(f"missing:{side}_max", f"{key[1:]} never states its {side} upper bound", self.d.decls.get(key))
        for v in [mn] + mx:
            if not _NAT.fullmatch(v):
                raise Invalid("literal", f"{key[1:]} {side} cardinality bound {v!r} is not a decimal integer")
        return {"min": int(mn), "max": "*" if star else int(mx[0])}
