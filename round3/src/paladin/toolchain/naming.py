"""Identifier mapping and IR type-expression -> Python annotation text (generation-time helpers)."""
from __future__ import annotations

import keyword
import re

PRIMITIVE = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "datetime": "str", "date": "str",
             "json": "Any", "bytes": "bytes"}


def ident(name: str) -> str:
    out = re.sub(r"\W", "_", name)
    if not out or out[0].isdigit() or keyword.iskeyword(out):
        out = "_" + out
    return out


def exact_ident(name: str) -> str:
    """A name that becomes a Python field / parameter must survive unchanged (it is also the wire name)."""
    if ident(name) != name:
        raise ValueError(f"IR name {name!r} is not usable as a Python field name")
    return name


def py_type(te) -> str:
    if isinstance(te, str):
        return PRIMITIVE[te]
    (ctor, inner), = te.items()
    if ctor == "ref":
        return "Key"
    if ctor == "list":
        return f"list[{py_type(inner)}]"
    if ctor == "optional":
        return f"Optional[{py_type(inner)}]"
    raise ValueError(f"unknown type expression {te!r}")


def enum_values(prop: dict):
    for c in prop.get("constraints", []) or []:
        if isinstance(c, str) and c.startswith("enum:"):
            return c[5:].split("|")
    return None


def prop_annotation(prop: dict) -> str:
    vals = enum_values(prop)
    base = "Literal[" + ", ".join(repr(v) for v in vals) + "]" if vals else py_type(prop["type"])
    if not prop.get("required", False) and not base.startswith("Optional["):
        base = f"Optional[{base}]"
    return base


def is_optional(te) -> bool:
    return isinstance(te, dict) and "optional" in te


def ref_target(te):
    """(declared type, is_list) when the expression is a (possibly optional / list of) reference, else None."""
    while isinstance(te, dict):
        (ctor, inner), = te.items()
        if ctor == "ref":
            return inner, False
        if ctor == "list":
            r = ref_target(inner)
            return (r[0], True) if r else None
        te = inner
    return None
