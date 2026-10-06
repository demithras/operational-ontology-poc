"""Atom-slot vocabulary of the OpenPona encoding: which rule's slot is an identifier, an opaque string or a literal.

Derived only from eoo_openpona.templates (the encoding table) -- nothing here reads the record."""
from __future__ import annotations

import re

from eoo_openpona.lines import n_slots, read_line
from eoo_openpona.templates import T

KEY = re.compile(r"L([1-9][0-9]*)\.a([1-9][0-9]*)")
INT_RULES = {"link.from_min", "link.from_max", "link.to_min", "link.to_max", "meta.int"}
FLOAT_RULES = {"meta.float"}
LITERAL_RULES = INT_RULES | FLOAT_RULES
IDENT = {"pkg.decl", "pkg.domain", "pkg.import", "pkg.ext", "pkg.meta", "meta.entry", "res.decl", "prop.decl", "fn.input"}
LITERAL_VALUE = {"pkg.version", "res.version", "meta.str"} | LITERAL_RULES
OPAQUE = {"obj.description", "prop.description", "prop.constraint", "iface.capability", "fn.impl", "act.precondition",
          "act.outcome", "pol.expression", "auth.principal", "auth.capability", "auth.resource", "obs.source",
          "con.scope", "con.expression", "eff.external_call", "eff.field_opaque"}


def slot_class(tid: str) -> str | None:
    if tid in IDENT:
        return "identifier"
    if tid in OPAQUE:
        return "opaque_string"
    if tid in LITERAL_VALUE:
        return "literal"
    return None


def atom_rule_ids() -> set[str]:
    return {t for t in T if n_slots(t) > 0}


def line_rules(text: str) -> list:
    return [read_line(i, ln) for i, ln in enumerate(text.splitlines(), 1)]


def record_vocabulary(text: str, rec: dict) -> dict:
    """Record-schema audit: every key must be an atom slot declared by a line; every declared slot must have a key."""
    lines = line_rules(text)
    declared = {f"L{ln.lineno}.a{k}" for ln in lines for k in range(1, n_slots(ln.tid) + 1)}
    bad_key = sorted(k for k in rec if not KEY.fullmatch(k))
    non_str = sorted(k for k, v in rec.items() if not isinstance(v, str))
    extra = sorted(set(rec) - declared - set(bad_key))
    missing = sorted(declared - set(rec))
    unclassified = sorted({ln.tid for ln in lines if n_slots(ln.tid) and slot_class(ln.tid) is None})
    cls: dict[str, int] = {}
    for ln in lines:
        c = slot_class(ln.tid)
        if c:
            cls[c] = cls.get(c, 0) + n_slots(ln.tid)
    return {"keys": len(rec), "declared_slots": len(declared), "non_atom_keys": bad_key, "non_string_values": non_str,
            "keys_not_declared_by_a_line": extra, "slots_without_key": missing,
            "atom_rules_without_class": unclassified, "slots_by_class": cls,
            "ok": not (bad_key or non_str or extra or missing or unclassified)}
