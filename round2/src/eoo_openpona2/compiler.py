"""OpenPona v2 text + atom record -> IR. Every single-valued field must be stated exactly once; nothing is
defaulted, inferred or taken from the record except atoms in the slots the lines declare; coreference between
lines is equality of bound atoms (ids are record metadata, H15 v2 prereg)."""
from __future__ import annotations

from eoo_ir.kinds import RESOURCE_ARRAYS
from eoo_ir.validate import Index, validate

from .ctx import _ABSENT, _C
from .document import PKG, read_document
from .errors import Ambiguous, Invalid, Unresolved
from .resources import _resource

_IR_ERR = {"schema": Invalid, "duplicate_id": Ambiguous, "duplicate_name": Ambiguous, "ambiguous_ref": Ambiguous,
           "unresolved_ref": Unresolved, "bad_primary_key": Invalid, "unknown_field": Invalid}


def _declared_subject(doc, key) -> bool:
    """The package always exists; every other subject must be declared by its own line."""
    return key == PKG or key in doc.decls


def compile(text: str, record: dict, *, check_ir: bool = True) -> dict:  # noqa: A001 - API name fixed by the spec
    doc = read_document(text, record)
    c = _C(doc)
    for (key, f), got in doc.facts.items():
        if not _declared_subject(doc, key):
            raise Unresolved("unresolved_binding", f"statement about {key[1:] if key else key} which is never declared",
                             got[0][0])
    for (_, parent), kids in doc.order.items():
        if parent[0] in ("res",) and parent not in doc.decls:
            raise Unresolved("unresolved_binding", f"{parent[1:]} is never declared", doc.decls[kids[0]])
    ir: dict = {"package_id": c.one(PKG, "package_id")}
    dom = c.one(PKG, "domain_id", required=False)
    if dom is not _ABSENT:
        ir["domain_id"] = dom
    ir["version"] = c.one(PKG, "version")
    iempty = c.all(PKG, "imports_empty")
    if doc.imports and iempty or len(iempty) > 1:
        raise Ambiguous("conflict:imports", "imports stated both empty and listed")
    if iempty or doc.imports:
        ir["imports"] = [s for _, s in doc.imports]
    for kind in RESOURCE_ARRAYS:
        ir[kind] = [_resource(c, kind, k, f"{kind}[{i}]") for i, k in enumerate(doc.order.get(("kind", kind), []))]
    present, md = doc.meta
    if present:
        ir["metadata"] = md
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
