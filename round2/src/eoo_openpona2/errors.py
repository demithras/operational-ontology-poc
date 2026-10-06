"""Typed errors of the OpenPona v2 surface (H15 v2). Every failure to compile or render is one of these.

``code`` names the specific rule that fired (e.g. ``missing:type``, ``conflict:required``,
``parse_ambiguous``); the class names the outcome family required by the H15 spec.
"""
from __future__ import annotations


class OpenPonaError(Exception):
    family = "error"

    def __init__(self, code: str, message: str, line: int | None = None):
        where = f"line {line}: " if line is not None else ""
        super().__init__(f"[{code}] {where}{message}")
        self.code = code
        self.message = message
        self.line = line


class Invalid(OpenPonaError):
    """The text/record states something no rule accepts (parse INVALID, unknown line shape,
    missing required statement, wrong reference role, dangling atom, ...)."""
    family = "invalid"


class Ambiguous(OpenPonaError):
    """More than one reading: parse AMBIGUOUS, an address declared twice, two statements
    for a single-valued field, or an IR string that would denote something else."""
    family = "ambiguous"


class Unresolved(OpenPonaError):
    """A binding with no candidate: a referenced address that is never declared, or an
    atom slot with no value in the record (canon/05: UNRESOLVED is a binding outcome)."""
    family = "unresolved"


class Unrepresentable(OpenPonaError):
    """render() was given an IR construct listed in ontology/openpona2_gaps.json."""
    family = "unrepresentable"


class InvalidIR(OpenPonaError):
    """render() was given a package that is not valid under eoo_ir.validate."""
    family = "invalid_ir"
