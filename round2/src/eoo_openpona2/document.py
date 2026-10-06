"""Text + record -> Document: matched lines, declarations, facts, blocks. No IR yet, no guessing.

Things are keyed by what the line states plus the bound atoms (coreference = equal atom values):
  ("pkg",)  ("res", kind, id)  ("prop", kind, owner_id, name)  ("param", kind, owner_id, name)  ("eff", action_id, n)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import Ambiguous, Invalid, Unresolved
from .facts import EFFECT_OPS, FACTS, META_RULES, TYPE_NODE_RULES
from .lines import Line, read_line
from .meta import MetaReader
from .vocab import RESOURCE_HEADS

KEY_RE = re.compile(r"L([1-9][0-9]*)\.a([1-9][0-9]*)")
PKG = ("pkg",)
HEAD_KIND = dict(RESOURCE_HEADS)  # head -> resource array (monkeypatch target of the swap mutant)


class Hole:
    """A constructed type announced by a bare `nasin`; filled by the next line."""
    def __init__(self, lineno: int):
        self.lineno, self.value = lineno, None


@dataclass
class Document:
    lines: list[Line]
    decls: dict = field(default_factory=dict)      # key -> declaring line
    order: dict = field(default_factory=dict)      # parent key / ("kind", kind) -> [child keys]
    facts: dict = field(default_factory=dict)      # (key, field) -> [(lineno, value)]
    imports: list = field(default_factory=list)    # [(lineno, import string)]
    meta: tuple = (False, None)


def split_lines(text: str) -> list[str]:
    if not isinstance(text, str):
        raise Invalid("text_type", f"text must be str, got {type(text).__name__}")
    body = text[:-1] if text.endswith("\n") else text
    raw = body.split("\n") if body else []
    for i, ln in enumerate(raw, 1):
        if not ln.strip():
            raise Invalid("blank_line", "one statement per line; blank lines are not statements", i)
        if "\r" in ln:
            raise Invalid("parse_invalid", "carriage return inside a line", i)
    return raw


def check_record(lines: list[Line], record) -> dict[str, str]:
    if not isinstance(record, dict):
        raise Invalid("record_type", f"record must be a mapping, got {type(record).__name__}")
    want = {f"L{ln.lineno}.a{j}" for ln in lines for j in range(1, ln.entry.n_atoms + 1)}
    for k, v in record.items():
        if not isinstance(k, str) or not KEY_RE.fullmatch(k):
            raise Invalid("record_key", f"record key {k!r} is not a neutral address 'L<line>.a<slot>'")
        if k not in want:
            raise Invalid("dangling_atom", f"record key {k!r} fills no atom slot any line declares")
        if not isinstance(v, str):
            raise Invalid("atom_type", f"record value at {k} must be a string atom, got {type(v).__name__}")
    missing = sorted(want - set(record), key=lambda s: tuple(int(x) for x in KEY_RE.fullmatch(s).groups()))
    if missing:
        raise Unresolved("missing_atom", f"atom slots with no bound value: {missing[:5]}")
    return record


def parts_of(ln: Line, rec: dict) -> list[tuple]:
    """[(part, atoms)] for every non-literal part, atoms taken left to right from the record."""
    out, j = [], 1
    for p in ln.entry.parts:
        if p.kind == "lit":
            continue
        out.append((p, [rec[f"L{ln.lineno}.a{j + k}"] for k in range(p.n)]))
        j += p.n
    return out


def ref_value(p, atoms: list) -> tuple:
    """A reference / type-ref part -> ('res', kind, id) | ('ext', import, name) | ('prop', kind, owner, name)."""
    alt = p.arg[1]
    if alt == "ext":
        return ("ext", atoms[1], atoms[0])
    if alt.startswith("prop:"):
        return ("prop", HEAD_KIND[alt[5:]], atoms[1], atoms[0])
    return ("res", HEAD_KIND[alt], atoms[0])


def type_value(p, atoms: list, lineno: int, holes: list):
    kind = p.arg[0]
    if kind == "prim":
        return ("prim", p.arg[1])
    if kind == "ref":
        return ("ref", ref_value(p, atoms), lineno)
    h = Hole(lineno)
    holes.append(h)
    return ("hole", h)


def _declare(d: Document, key: tuple, parent: tuple, lineno: int) -> None:
    if key in d.decls:
        raise Ambiguous("duplicate_declaration", f"{key[1:]} is declared twice (lines {d.decls[key]} and {lineno})", lineno)
    d.decls[key] = lineno
    d.order.setdefault(parent, []).append(key)


def _fact(d: Document, key: tuple, name: str, lineno: int, val) -> None:
    d.facts.setdefault((key, name), []).append((lineno, val))


def read_document(text: str, record) -> Document:
    lines = [read_line(i, t) for i, t in enumerate(split_lines(text), 1)]
    rec = check_record(lines, record)
    d = Document(lines)
    mr = MetaReader()
    pending: Hole | None = None
    open_eff = None
    for ln in lines:
        rid, n = ln.rid, ln.lineno
        ps = parts_of(ln, rec)
        by = {}
        for p, at in ps:
            by.setdefault(p.kind, []).append((p, at))
        if pending is not None and rid not in TYPE_NODE_RULES:
            raise Invalid("missing:type_node", f"the constructed type announced on line {pending.lineno} is never stated", n)
        if pending is None and rid in TYPE_NODE_RULES:
            raise Invalid("dangling_type_node", "a type statement (bare nasin) with no announced type before it", n)
        if mr.open() and rid not in META_RULES:
            raise Invalid("unclosed:metadata", "a metadata value is still open", n)
        if rid in ("eff.field", "eff.fields_empty") and open_eff is None:
            raise Invalid("dangling_statement", "a field statement (ante li ma ..) that follows no effect statement", n)
        if rid not in ("eff.field", "eff.fields_empty"):
            open_eff = None
        new_holes: list[Hole] = []
        subj = next((("res", HEAD_KIND[p.arg], at[0]) for p, at in by.get("subj", [])), None)
        ctx = next((("res", HEAD_KIND[p.arg], at[0]) for p, at in by.get("ctx", [])), None)
        atom = next((at[0] for k in ("val", "ni", "pkg", "imp") for _, at in by.get(k, [])), None)
        name = next((at[0] for k in ("prop", "param") for _, at in by.get(k, [])), None)
        tval = next((type_value(p, at, n, new_holes) for p, at in by.get("type", [])), None)
        if rid in TYPE_NODE_RULES:
            pending.value = (TYPE_NODE_RULES[rid], tval)
            pending = None
        elif rid in META_RULES:
            mr.line(rid, atom, n)
        elif rid == "res.decl":
            p, at = by["decl"][0]
            kind = HEAD_KIND[p.arg]
            _declare(d, ("res", kind, at[0]), ("kind", kind), n)
        elif rid == "prop.decl":
            _declare(d, ("prop", subj[1], subj[2], name), ("props", subj), n)
        elif rid == "param.decl":
            _declare(d, ("param", subj[1], subj[2], name), ("params", subj), n)
        elif rid in EFFECT_OPS:
            key = ("eff", subj[2], len(d.order.get(("effects", subj), [])))
            _declare(d, key, ("effects", subj), n)
            _fact(d, key, "op", n, EFFECT_OPS[rid])
            refs = by.get("ref", [])
            _fact(d, key, "target", n, ref_value(*refs[0]) if refs else ("opaque", atom))
            open_eff = key
        elif rid == "pkg.import":
            d.imports.append((n, atom))
        else:
            whose, fname, spec = FACTS[rid]
            key = {"pkg": PKG, "subj": subj, "eff": open_eff,
                   "prop": ("prop", ctx[1], ctx[2], name) if ctx else None,
                   "param": ("param", ctx[1], ctx[2], name) if ctx else None}[whose]
            if spec == "atom":
                val = atom
            elif spec == "name":
                val = name
            elif spec == "type":
                val = tval
            elif spec == "ref":
                refs = [ref_value(p, at) for p, at in by["ref"]]
                val = tuple(refs) if len(refs) > 1 else refs[0]
            else:
                val = spec
            _fact(d, key, fname, n, val)
        if new_holes:
            pending = new_holes[0]
    last = len(lines)
    if pending is not None:
        raise Invalid("missing:type_node", f"the constructed type announced on line {pending.lineno} is never stated", last)
    d.meta = mr.result(last)
    return d
