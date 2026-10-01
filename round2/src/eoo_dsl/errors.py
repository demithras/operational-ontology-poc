"""Typed errors of the direct typed DSL baseline. Every failure to compile is one of these."""
from __future__ import annotations


class DslError(Exception):
    code = "dsl_error"

    def __init__(self, message: str, path: str = ""):
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path
        self.message = message


class DslSyntaxError(DslError):
    code = "syntax"


class DslSurfaceAmbiguity(DslError):
    """The text itself is ambiguous: duplicate keys, anchors/aliases/tags, several documents."""
    code = "surface_ambiguous"


class DslDuplicateKey(DslSurfaceAmbiguity):
    code = "duplicate_key"


class DslAliasError(DslSurfaceAmbiguity):
    code = "alias_anchor_tag"


class DslMissingField(DslError):
    code = "missing_field"


class DslUnknownKey(DslError):
    code = "unknown_key"


class DslTypeError(DslError):
    code = "type"


class DslEnumError(DslError):
    code = "enum"


class DslConstraintError(DslError):
    code = "constraint"


class DslUnresolvedReference(DslError):
    code = "unresolved_ref"


class DslAmbiguousReference(DslError):
    code = "ambiguous_ref"


class DslDuplicateId(DslError):
    code = "duplicate"
