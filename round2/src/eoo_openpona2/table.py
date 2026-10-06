"""Expansion of the frozen phrase table into the finite set of concrete lines it licenses.

A v2 line contains no atoms (every value is a `ni` bound in the record), so the table expands to a finite
set of exact token strings. LINES maps each string to its (rule id, parts); a line is accepted only if it is
one of these strings (meaning rule: every line instantiates a row). table_size() = len(LINES) is the bound the
bounded-vocabulary test compares against.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from functools import lru_cache

from .phrases import T
from .vocab import EXT_TOKENS, PRIMITIVE_PHRASES, ROLES

_PH = re.compile(r"\{(\w+)(?::([\w,]+))?\}")


@dataclass(frozen=True)
class Part:
    kind: str   # pkg imp decl subj ctx prop param val ni ref type lit
    arg: object = None
    n: int = 0  # number of atoms this part binds


def _ref_alts(alt: str, role: str) -> tuple:
    if alt == "ext":
        return EXT_TOKENS, 2
    if alt.startswith("prop:"):
        return ("sona", "ni", "pi", alt[5:], "ni"), 2
    return (alt, "ni"), 1


def _alternatives(tok: str) -> list[tuple[tuple, Part]]:
    m = _PH.fullmatch(tok)
    if not m:
        return [((tok,), Part("lit", tok))]
    kind, arg = m.group(1), m.group(2)
    if kind == "PKG":
        return [(("kulupu", "ni"), Part("pkg", None, 1))]
    if kind == "IMP":
        return [(("kulupu", "ni"), Part("imp", None, 1))]
    if kind in ("D", "S", "C"):
        k = {"D": "decl", "S": "subj", "C": "ctx"}[kind]
        return [((h, "ni"), Part(k, h, 1)) for h in arg.split(",")]
    if kind == "P":
        return [(("sona", "ni"), Part("prop", None, 1))]
    if kind == "K":
        return [(("kute", "ni"), Part("param", None, 1))]
    if kind == "V":
        return [((arg, "ni"), Part("val", arg, 1))]
    if kind == "NI":
        return [(("ni",), Part("ni", None, 1))]
    if kind == "R":
        out = []
        for alt in ROLES[arg]:
            toks, n = _ref_alts(alt, arg)
            out.append((toks, Part("ref", (arg, alt), n)))
        return out
    if kind == "TYPE":
        out = [(ph, Part("type", ("prim", name), 0)) for name, ph in PRIMITIVE_PHRASES.items()]
        for alt in ROLES["typeref"]:
            toks, n = _ref_alts(alt, "typeref")
            out.append((toks, Part("type", ("ref", alt), n)))
        out.append((("nasin",), Part("type", ("node",), 0)))
        return out
    raise AssertionError(f"unknown placeholder {tok}")  # pragma: no cover - table error


@dataclass(frozen=True)
class Entry:
    rid: str
    parts: tuple  # Part per pattern position (literals included)

    @property
    def n_atoms(self) -> int:
        return sum(p.n for p in self.parts)


def expand(rid: str) -> list[tuple[str, Entry]]:
    slots = [_alternatives(tok) for tok in T[rid][0].split()]
    out = []
    for combo in itertools.product(*slots):
        text = " ".join(t for toks, _ in combo for t in toks)
        out.append((text, Entry(rid, tuple(p for _, p in combo))))
    return out


@lru_cache(maxsize=1)
def lines() -> dict[str, Entry]:
    table: dict[str, Entry] = {}
    for rid in T:
        for text, e in expand(rid):
            if text in table:
                raise AssertionError(f"phrase table is ambiguous: {text!r} instantiates {table[text].rid} and {rid}")
            table[text] = e
    return table


def table_size() -> int:
    """Number of distinct concrete lines the frozen table licenses (the bounded-vocabulary bound)."""
    return len(lines())


def rule_line_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for e in lines().values():
        out[e.rid] = out.get(e.rid, 0) + 1
    return out
