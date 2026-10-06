"""Compilation context: facts lookup (exactly-once rule), references, types, properties, parameters."""
from __future__ import annotations

import re

from .document import Document
from .errors import Ambiguous, Invalid, Unresolved

ENDPOINT = ("object_types", "interfaces")
EFFECT_KINDS = {"create": ("object_types",), "update": ("object_types",), "delete": ("object_types",),
                "link": ("link_types",), "unlink": ("link_types",), "git_change": ("object_types", "link_types")}
_NAT = re.compile(r"0|[1-9][0-9]*")


class _C:
    def __init__(self, doc: Document, rec: dict):
        self.d = doc
        self.rec = rec
        self.by_line = {ln.lineno: ln for ln in doc.lines}
        self.checks: list[tuple] = []  # (path, string, kinds, prefix, allow_prop, expected)
        self.type_uses: dict[str, int] = {}
        self.ext_uses: set[str] = set()
        self.used: set[tuple[str, str]] = set()

    def line(self, n: int):
        return self.by_line[n]

    # ------------------------------------------------------------ facts
    def all(self, a: str, f: str) -> list:
        self.used.add((a, f))
        return [v for _, v in self.d.facts.get((a, f), [])]

    def raw(self, a: str, f: str) -> list:
        self.used.add((a, f))
        return self.d.facts.get((a, f), [])

    def one(self, a: str, f: str, required: bool = True):
        self.used.add((a, f))
        got = self.d.facts.get((a, f), [])
        if len(got) > 1:
            raise Ambiguous(f"conflict:{f}", f"{a!r} states {f} {len(got)} times", got[1][0])
        if not got:
            if required:
                raise Invalid(f"missing:{f}", f"{a!r} never states {f}", self.d.decls[a].line if a in self.d.decls else None)
            return _ABSENT
        return got[0][1]

    def children(self, parent: str, what: str) -> list[str]:
        return [a for a in self.d.order if self.d.decls[a].parent == parent and self.d.decls[a].what == what]

    def decl(self, a: str, line_hint=None):
        if a not in self.d.decls:
            raise Unresolved("unresolved_address", f"address {a!r} is never declared", line_hint)
        return self.d.decls[a]

    # ------------------------------------------------------------ references
    def ref(self, a: str, kinds, prefix: str = "", allow_prop: bool = False, path: str = "") -> str:
        dc = self.decl(a)
        if dc.what == "external":
            self.ext_uses.add(a)
            imp = self.decl(dc.refs[0][1])
            s, expected = f"{imp.atom}#{dc.atom}", ("import", imp.atom)
        elif dc.what == "property":
            owner = self.decl(dc.parent)
            if not allow_prop or owner.what not in kinds:
                raise Invalid("reference_role", f"{a!r} (property of {owner.what}) cannot fill {path}", dc.line)
            s, expected = f"{owner.atom}.{dc.atom}", (owner.what, owner.atom, dc.atom)
        elif dc.what in kinds:
            s, expected = prefix + dc.atom, (dc.what, dc.atom)
        else:
            raise Invalid("reference_role", f"{a!r} is a {dc.what}; {path} needs one of {kinds}", dc.line)
        self.checks.append((path, s, kinds, prefix, allow_prop, expected))
        return s

    def own_prop(self, a: str, owner: str, path: str) -> str:
        dc = self.decl(a)
        if dc.what != "property" or dc.parent != owner:
            raise Invalid("reference_role", f"{path}: {a!r} is not a property of {owner!r}", dc.line)
        return dc.atom

    def type_(self, tv, path: str, seen=()):
        kind, val = tv
        if kind == "prim":
            return val
        dc = self.decl(val)
        if dc.what != "type_node":
            return {"ref": self.ref(val, ENDPOINT, path=path)}
        if val in seen:
            raise Invalid("type_cycle", f"type node {val!r} contains itself", dc.line)
        self.type_uses[val] = self.type_uses.get(val, 0) + 1
        ctor = self.one(val, "ctor")
        inner = self.type_(self.one(val, "type"), f"{path}.{ctor}", seen + (val,))
        return {ctor: inner}

    # ------------------------------------------------------------ pieces
    def prop(self, a: str, path: str) -> dict:
        p = {"name": self.decl(a).atom, "type": self.type_(self.one(a, "type"), path + ".type"),
             "required": self.one(a, "required")}
        for f in ("immutable", "description"):
            v = self.one(a, f, required=False)
            if v is not _ABSENT:
                p[f] = v
        cs, empty = self.all(a, "constraints"), self.all(a, "constraints_empty")
        if cs and empty or len(empty) > 1:
            raise Ambiguous("conflict:constraints", f"{a!r} states both empty and listed constraints")
        if empty:
            p["constraints"] = []
        elif cs:
            p["constraints"] = cs
        return p

    def props(self, owner: str, path: str) -> list[dict]:
        return [self.prop(a, f"{path}[{i}]") for i, a in enumerate(self.children(owner, "property"))]

    def params(self, owner: str, path: str) -> list[dict]:
        out = []
        for i, a in enumerate(self.children(owner, "parameter")):
            p = {"name": self.decl(a).atom, "type": self.type_(self.one(a, "type"), f"{path}[{i}].type")}
            r = self.one(a, "required", required=False)
            if r is not _ABSENT:
                p["required"] = r
            out.append(p)
        return out

    def card(self, a: str, side: str) -> dict:
        mn = self.one(a, side + "_min")
        mx, star = self.all(a, side + "_max"), self.all(a, side + "_star")
        if len(mx) + len(star) > 1:
            raise Ambiguous(f"conflict:{side}_max", f"{a!r} states its {side} upper bound more than once")
        if not mx and not star:
            raise Invalid(f"missing:{side}_max", f"{a!r} never states its {side} upper bound", self.d.decls[a].line)
        for v in [mn] + mx:
            if not _NAT.fullmatch(v):
                raise Invalid("literal", f"{a!r} {side} cardinality bound {v!r} is not a decimal integer")
        return {"min": int(mn), "max": "*" if star else int(mx[0])}


class _Absent:
    def __repr__(self):
        return "<absent>"


_ABSENT = _Absent()
