"""OpenPona text + atom record -> IR. Every single-valued field must be stated exactly once; nothing is
defaulted, inferred or taken from the record except atoms in the slots the lines declare."""
from __future__ import annotations

import json
import math
import re

from eoo_ir.kinds import RESOURCE_ARRAYS
from eoo_ir.validate import Index, validate

from .ctx import _ABSENT, _C
from .document import PKG, read_document
from .errors import Ambiguous, Invalid, Unresolved
from .resources import _resource

_INT = re.compile(r"-?(0|[1-9][0-9]*)")
_IR_ERR = {"schema": Invalid, "duplicate_id": Ambiguous, "duplicate_name": Ambiguous, "ambiguous_ref": Ambiguous,
           "unresolved_ref": Unresolved, "bad_primary_key": Invalid, "unknown_field": Invalid}


def _scalar(v, a: str):
    if not isinstance(v, tuple):
        return v  # True / False / None, stated by the line itself
    kind, s = v
    if kind == "str":
        return s
    if kind == "int":
        if not _INT.fullmatch(s):
            raise Invalid("literal", f"{a!r}: {s!r} is not a canonical decimal integer")
        return int(s)
    try:
        f = float(s)
    except ValueError:
        raise Invalid("literal", f"{a!r}: {s!r} is not a number literal") from None
    if not math.isfinite(f) or json.dumps(f) != s:
        raise Invalid("literal", f"{a!r}: {s!r} is not the canonical JSON spelling of a finite non-integer number")
    return f


def _meta(c: _C, a: str):
    kids = c.children(a, "meta_node")
    entries = [k for k in kids if c.d.decls[k].tid in ("meta.entry", "pkg.meta")]
    items = [k for k in kids if c.d.decls[k].tid == "meta.item"]
    scal = c.all(a, "scalar")
    oe = c.all(a, "obj_empty" if a != PKG else "meta_empty")
    le = c.all(a, "list_empty") if a != PKG else []
    shapes = [bool(scal), bool(entries or oe), bool(items or le)]
    if sum(shapes) > 1 or len(scal) > 1 or len(oe) > 1 or len(le) > 1 or (oe and entries) or (le and items):
        raise Ambiguous("conflict:metadata", f"{a!r} states more than one JSON value")
    if not any(shapes):
        raise Invalid("missing:metadata", f"{a!r} states no JSON value", c.d.decls[a].line if a in c.d.decls else None)
    if scal:
        return _scalar(scal[0], a)
    if items or le:
        return [_meta(c, k) for k in items]
    out = {}
    for k in entries:
        key = c.d.decls[k].atom
        if key in out:
            raise Ambiguous("duplicate_key", f"metadata key {key!r} stated twice under {a!r}", c.d.decls[k].line)
        out[key] = _meta(c, k)
    return out


def compile(text: str, record: dict, *, check_ir: bool = True) -> dict:  # noqa: A001 - API name fixed by the spec
    doc = read_document(text, record)
    c = _C(doc, record)
    for (subj, f), got in doc.facts.items():
        if subj != PKG and subj not in doc.decls:
            raise Unresolved("unresolved_address", f"address {subj!r} is never declared", got[0][0])
    ir: dict = {"package_id": c.one(PKG, "package_id")}
    dom = c.one(PKG, "domain_id", required=False)
    if dom is not _ABSENT:
        ir["domain_id"] = dom
    ir["version"] = c.one(PKG, "version")
    imps, iempty = c.children(PKG, "import"), c.all(PKG, "imports_empty")
    if imps and iempty or len(iempty) > 1:
        raise Ambiguous("conflict:imports", "imports stated both empty and listed")
    if iempty or imps:
        ir["imports"] = [doc.decls[a].atom for a in imps]
    for kind in RESOURCE_ARRAYS:
        ir[kind] = [_resource(c, kind, a, f"{kind}[{i}]")
                    for i, a in enumerate(x for x in doc.order if doc.decls[x].what == kind)]
    if c.children(PKG, "meta_node") or doc.facts.get((PKG, "meta_empty")):
        ir["metadata"] = _meta(c, PKG)
    for a, dc in doc.decls.items():
        if dc.what == "type_node" and c.type_uses.get(a, 0) != 1:
            raise Invalid("dangling_address" if not c.type_uses.get(a) else "shared_type_node",
                          f"type node {a!r} is used {c.type_uses.get(a, 0)} times (exactly once required)", dc.line)
        if dc.what == "external" and a not in c.ext_uses:
            raise Invalid("dangling_address", f"external name {a!r} is declared but never referenced", dc.line)
    unused = [(k, v[0][0]) for k, v in doc.facts.items() if k not in c.used]
    if unused:
        raise Invalid("unused_statement", f"statement about {unused[0][0]} is not part of any IR field", unused[0][1])
    if check_ir:
        _check_ir(c, ir)
    return ir


def _check_ir(c: _C, ir: dict) -> None:
    errs = validate(ir)
    if errs:
        e = errs[0]
        raise _IR_ERR.get(e.code, Invalid)(f"ir:{e.code}", f"{e.path}: {e.message}")
    ix = Index(ir)
    for path, s, kinds, prefix, allow_prop, expected in c.checks:
        got = ix.resolve(s, kinds, prefix, allow_prop)
        if got != [expected]:
            raise Ambiguous("denotation", f"{path}: the line names {expected}, but the IR string {s!r} "
                            f"would denote {got}")
