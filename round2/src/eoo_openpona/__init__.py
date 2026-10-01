"""H15 candidate surface: OpenPona (pinned) <-> frozen EOO IR.

render(ir) -> (text, record); compile(text, record) -> ir. The record holds atoms only, keyed by
neutral positional addresses 'L<line>.a<slot>'; everything structural is in the lines.
"""
from .compiler import compile
from .errors import Ambiguous, Invalid, InvalidIR, OpenPonaError, Unrepresentable, Unresolved
from .record import dump_record, load_record
from .render import render

__all__ = ["Ambiguous", "Invalid", "InvalidIR", "OpenPonaError", "Unrepresentable", "Unresolved",
           "compile", "dump_record", "load_record", "render"]
