"""Metadata block reader: a JSON value written as nested open/close statements (no labels).

`kulupu li sona e sitelen ni` opens a package metadata member; `sitelen li sona e sitelen ni` /
`sitelen li linja e sitelen` open a member / an item of the value currently open; a scalar statement fills the
open value and completes it; `sitelen li pini` completes an open object or array. Nothing is defaulted: a value
that is opened and never stated, or a block left open, is an error.
"""
from __future__ import annotations

import json
import math
import re

from .errors import Ambiguous, Invalid

_INT = re.compile(r"-?(0|[1-9][0-9]*)")
FRESH, OBJ, ARR = "fresh", "object", "array"
SCALARS = {"meta.true": True, "meta.false": False, "meta.null": None}


class _Node:
    def __init__(self, put):
        self.state, self.value, self.put = FRESH, None, put


def scalar(rid: str, atom: str | None, lineno: int):
    if rid in SCALARS:
        return SCALARS[rid]
    if rid == "meta.str":
        return atom
    if rid == "meta.int":
        if not _INT.fullmatch(atom):
            raise Invalid("literal", f"{atom!r} is not a canonical decimal integer", lineno)
        return int(atom)
    try:
        f = float(atom)
    except ValueError:
        raise Invalid("literal", f"{atom!r} is not a number literal", lineno) from None
    if not math.isfinite(f) or json.dumps(f) != atom:
        raise Invalid("literal", f"{atom!r} is not the canonical JSON spelling of a finite non-integer number", lineno)
    return f


class MetaReader:
    def __init__(self):
        self.stack: list[_Node] = []
        self.members: dict = {}
        self.member_lines: list[int] = []
        self.empty_lines: list[int] = []

    def open(self) -> bool:
        return bool(self.stack)

    def _top(self, lineno: int) -> _Node:
        if not self.stack:
            raise Invalid("dangling_metadata", "a metadata statement with no open value", lineno)
        return self.stack[-1]

    def _done(self, node: _Node, value) -> None:
        node.value = value
        node.put(value)
        self.stack.pop()

    def line(self, rid: str, atom, lineno: int) -> None:
        if rid == "pkg.meta":
            if self.stack:
                raise Invalid("unclosed:metadata", "a package metadata member starts while a value is still open", lineno)
            if atom in self.members:
                raise Ambiguous("duplicate_key", f"metadata key {atom!r} stated twice", lineno)
            self.members[atom] = None
            self.member_lines.append(lineno)
            self.stack.append(_Node(lambda v, k=atom: self.members.__setitem__(k, v)))
            return
        if rid == "pkg.meta_empty":
            self.empty_lines.append(lineno)
            return
        top = self._top(lineno)
        if rid in SCALARS or rid in ("meta.int", "meta.float", "meta.str"):
            if top.state != FRESH:
                raise Ambiguous("conflict:metadata", "a scalar stated for a value that is already an object/array", lineno)
            self._done(top, scalar(rid, atom, lineno))
        elif rid in ("meta.obj_empty", "meta.list_empty"):
            if top.state != FRESH:
                raise Ambiguous("conflict:metadata", "an empty value stated for a value that has members/items", lineno)
            self._done(top, {} if rid == "meta.obj_empty" else [])
        elif rid == "meta.entry":
            if top.state == FRESH:
                top.state, top.value = OBJ, {}
            elif top.state != OBJ:
                raise Ambiguous("conflict:metadata", "an object member stated for an array value", lineno)
            if atom in top.value:
                raise Ambiguous("duplicate_key", f"metadata key {atom!r} stated twice in one object", lineno)
            top.value[atom] = None
            self.stack.append(_Node(lambda v, d=top.value, k=atom: d.__setitem__(k, v)))
        elif rid == "meta.item":
            if top.state == FRESH:
                top.state, top.value = ARR, []
            elif top.state != ARR:
                raise Ambiguous("conflict:metadata", "an array item stated for an object value", lineno)
            top.value.append(None)
            self.stack.append(_Node(lambda v, d=top.value, i=len(top.value) - 1: d.__setitem__(i, v)))
        elif rid == "meta.close":
            if top.state == FRESH:
                raise Invalid("missing:metadata", "a metadata value is closed before any value is stated", lineno)
            self._done(top, top.value)
        else:  # pragma: no cover - dispatch error
            raise AssertionError(rid)

    def result(self, last_line: int):
        """(present, value) of package metadata; raises on an unclosed block or a conflict."""
        if self.stack:
            raise Invalid("unclosed:metadata", "a metadata value is still open at the end of the block", last_line)
        if self.empty_lines and self.member_lines or len(self.empty_lines) > 1:
            raise Ambiguous("conflict:metadata", "package metadata stated both empty and with members",
                            (self.empty_lines + self.member_lines)[-1])
        if self.empty_lines:
            return True, {}
        if self.member_lines:
            return True, self.members
        return False, None
