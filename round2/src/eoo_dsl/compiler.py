"""DSL text -> IR dict. Fails closed with typed errors; never guesses, defaults or repairs."""
from __future__ import annotations

from eoo_ir.validate import referential_errors

from .errors import (DslAmbiguousReference, DslDuplicateId, DslError, DslSyntaxError, DslUnresolvedReference)
from .loader import load
from .spec import PACKAGE, check

_REF_ERRORS = {
    "unresolved_ref": DslUnresolvedReference, "bad_primary_key": DslUnresolvedReference,
    "unknown_field": DslUnresolvedReference, "ambiguous_ref": DslAmbiguousReference,
    "duplicate_id": DslDuplicateId, "duplicate_name": DslDuplicateId,
}


def compile(text: str) -> dict:  # noqa: A001 - the API name fixed by the H15 spec
    doc = load(text)
    if not isinstance(doc, dict):
        raise DslSyntaxError(f"the document root must be a mapping, got {type(doc).__name__}")
    check(doc, PACKAGE, "")
    errs = referential_errors(doc)
    if errs:
        e = errs[0]
        raise _REF_ERRORS.get(e.code, DslError)(e.message, e.path)
    return doc
