"""Project Ontology logic bindings: every IR ref (function / policy / constraint / precondition / outcome / payload /
resource_selector)."""
from __future__ import annotations

from typing import Optional

from eoo_engine import LogicBindings

from . import actions, constraints, functions, policies, selectors
from .derive import Deriver, Evaluator
from .freeze import BlobReader, git_blob_reader


def build_bindings(ir: dict, evaluators: dict[str, Evaluator], reader: Optional[BlobReader] = None,
                   deriver: Optional[Deriver] = None) -> LogicBindings:
    reader = reader or git_blob_reader()
    deriver = deriver or Deriver(evaluators)
    b = LogicBindings()
    tables = {"function": functions.make(deriver, reader), "policy": policies.make(deriver, reader),
              "constraint": constraints.make(ir, deriver), "resource_selector": selectors.make(ir)}
    tables.update(actions.bindings(deriver, reader, ir))
    for kind, table in tables.items():
        for key, fn in table.items():
            b.bind(kind, key, fn)
    return b
