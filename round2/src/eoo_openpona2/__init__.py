"""H15 v2 candidate surface: OpenPona (pinned) <-> frozen EOO IR, with no coreference labels.

render(ir) -> (text, record); compile(text, record) -> ir. Every thing is written as its kind head plus `ni`
('this <head>, bound in the record'); the record holds the identifiers and other atoms under neutral positional
keys 'L<line>.a<slot>'; coreference between lines is equality of record atoms. Every line is one concrete
instance of the frozen phrase table (src/eoo_openpona2/phrases.py, ontology/openpona2_encoding.md).
"""
from .compiler import compile
from .errors import Ambiguous, Invalid, InvalidIR, OpenPonaError, Unrepresentable, Unresolved
from .record import dump_record, load_record
from .render import render

__all__ = ["Ambiguous", "Invalid", "InvalidIR", "OpenPonaError", "Unrepresentable", "Unresolved",
           "compile", "dump_record", "load_record", "render"]
