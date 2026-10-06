"""Manufacturing logic bindings: every IR ref (function / policy / constraint / precondition / outcome / payload)."""
from __future__ import annotations

from paladin.engine import LogicBindings

from . import actions, constraints, functions, policies


def build_bindings() -> LogicBindings:
    b = LogicBindings()
    for kind, table in (("function", functions.IMPLEMENTATIONS), ("policy", policies.IMPLEMENTATIONS),
                        ("constraint", constraints.IMPLEMENTATIONS), ("precondition", actions.PRECONDITIONS),
                        ("outcome_predicate", actions.OUTCOMES), ("payload", actions.PAYLOADS)):
        for key, fn in table.items():
            b.bind(kind, key, fn)
    return b
